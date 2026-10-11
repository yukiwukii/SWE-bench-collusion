"""Summarize one experiment directory written by run_experiment.sh.

    python3 helper_code/summarize_results.py results/<name>

Reads <dir>/agent/*/result.json and, if present, <dir>/regrade/*/result.json, and writes
<dir>/summary.json, <dir>/per_task.csv and <dir>/calls.csv. The re-graded result is the headline score when available.

Per-task cost, best source first:
  openrouter_reported  sum of OpenRouter's own usage.cost over the task's LLM calls (mini-swe-agent trajectories)
  list_price_estimate  task tokens x the model's OpenRouter list prices (<dir>/pricing.json)
  agent_reported       the agent's own figure (often priced off a non-OpenRouter table, or missing)
The experiment total billed comes from <dir>/cost_log.json (OpenRouter key usage before/after each run).

Prompt caching, per call (calls.csv) and summed per task / experiment:
  cache_hit_tokens   input tokens served from the provider's prompt cache (cheap)
  cache_miss_tokens  input tokens processed in full (prompt_tokens - cache_hit_tokens)
  cache_write_tokens the part of the misses written to the cache (only some providers report or charge it)
  cache_hit_rate     cache_hit_tokens / prompt_tokens
  calls_with_cache_hit  calls where at least one input token came from the cache
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "v2" / "tooling"))
from openrouter_pricing import estimate_cost  # noqa: E402

CALL_COLS = ["task", "call", "provider", "prompt_tokens", "cache_hit_tokens", "cache_miss_tokens",
             "cache_write_tokens", "output_tokens", "cost_usd"]


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def llm_calls(agent_dir):
    """One dict per LLM call: from mini-swe-agent's trajectory (raw OpenRouter responses, exact cost),
    else from harbor's ATIF trajectory.json (Claude Code, Codex)."""
    calls = []
    traj = read_json(agent_dir / "mini-swe-agent.trajectory.json")
    if traj:
        for m in traj.get("messages", []):
            r = (m.get("extra") or {}).get("response")
            if not isinstance(r, dict):
                continue
            u = r.get("usage") or {}
            d = u.get("prompt_tokens_details") or {}
            calls.append({"provider": r.get("provider"), "prompt_tokens": u.get("prompt_tokens") or 0,
                          "cache_hit_tokens": d.get("cached_tokens") or 0,
                          "cache_write_tokens": d.get("cache_write_tokens") or d.get("cache_creation_tokens") or 0,
                          "output_tokens": u.get("completion_tokens") or 0, "cost_usd": u.get("cost")})
        return calls
    traj = read_json(agent_dir / "trajectory.json") or {}
    for step in traj.get("steps", []):
        mt = step.get("metrics") or {}
        if step.get("source") != "agent" or mt.get("prompt_tokens") is None:
            continue
        calls.append({"provider": None, "prompt_tokens": mt.get("prompt_tokens") or 0,
                      "cache_hit_tokens": mt.get("cached_tokens") or 0,
                      "cache_write_tokens": (mt.get("extra") or {}).get("cache_creation_input_tokens") or 0,
                      "output_tokens": mt.get("completion_tokens") or 0, "cost_usd": None})
    return calls


def cache_stats(calls):
    prompt = sum(c["prompt_tokens"] for c in calls)
    hit = sum(c["cache_hit_tokens"] for c in calls)
    return {
        "cache_hit_tokens": hit,
        "cache_miss_tokens": prompt - hit,
        "cache_write_tokens": sum(c["cache_write_tokens"] for c in calls),
        "cache_hit_rate": round(hit / prompt, 4) if prompt else None,
        "calls_with_cache_hit": sum(1 for c in calls if c["cache_hit_tokens"] > 0),
    }


def load_trials(job_dir, pricing=None, call_log=None):
    trials = {}
    for rj in sorted(job_dir.glob("*/result.json")):
        r = json.loads(rj.read_text())
        rewards = (r.get("verifier_result") or {}).get("rewards") or {}
        agent = r.get("agent_result") or {}
        task = r["task_name"].split("/")[-1]
        t = {
            "reward": rewards.get("reward"),
            "error": (r.get("exception_info") or {}).get("exception_type"),
            "input_tokens": agent.get("n_input_tokens"),
            "output_tokens": agent.get("n_output_tokens"),
            "agent_reported_usd": agent.get("cost_usd"),
        }
        if pricing is not None:  # agent phase: work out the task's cost and caching
            calls = llm_calls(rj.parent / "agent")
            for i, c in enumerate(calls, 1):
                c["cache_miss_tokens"] = c["prompt_tokens"] - c["cache_hit_tokens"]
                if call_log is not None:
                    call_log.append({"task": task, "call": i, **c})
            t["n_llm_calls"] = len(calls) or None
            if calls:
                t.update(cache_stats(calls))
            else:  # no per-call log: fall back to harbor's per-task totals
                hit = agent.get("n_cache_tokens") or 0
                t.update(cache_hit_tokens=hit, cache_write_tokens=0, calls_with_cache_hit=None,
                         cache_miss_tokens=(t["input_tokens"] - hit) if t["input_tokens"] is not None else None,
                         cache_hit_rate=round(hit / t["input_tokens"], 4) if t["input_tokens"] else None)
            reported = [c["cost_usd"] for c in calls if c["cost_usd"] is not None]
            t["openrouter_reported_usd"] = round(sum(reported), 6) if reported else None
            t["list_price_estimate_usd"] = (
                round(estimate_cost(pricing, t["input_tokens"], t["output_tokens"] or 0,
                                    t["cache_hit_tokens"] or 0, t["cache_write_tokens"] or 0), 6)
                if pricing and t["input_tokens"] is not None else None)
            for source in ("openrouter_reported", "list_price_estimate", "agent_reported"):
                if t[f"{source}_usd"] is not None:
                    t["cost_usd"], t["cost_source"] = t[f"{source}_usd"], source
                    break
            else:
                t["cost_usd"], t["cost_source"] = None, None
        trials[task] = t
    return trials


def score(trials):
    resolved = sum(1 for t in trials.values() if (t["reward"] or 0) >= 1)
    return {
        "n_trials": len(trials),
        "resolved": resolved,
        "resolve_rate": round(resolved / len(trials), 4) if trials else None,
        "errors": sum(1 for t in trials.values() if t["error"]),
    }


def cost_summary(out, trials):
    pricing = read_json(out / "pricing.json") or {}
    log = read_json(out / "cost_log.json") or []
    billed = [e["billed_usd"] for e in log if "billed_usd" in e]
    costs = [t["cost_usd"] for t in trials.values() if t.get("cost_usd") is not None]
    sources = {}
    for t in trials.values():
        sources[t.get("cost_source") or "unknown"] = sources.get(t.get("cost_source") or "unknown", 0) + 1
    return {
        "model": pricing.get("model"),
        "total_billed_usd": round(sum(billed), 6) if billed else None,
        "sum_of_per_task_usd": round(sum(costs), 6) if costs else None,
        "mean_per_task_usd": round(sum(costs) / len(costs), 6) if costs else None,
        "max_per_task_usd": round(max(costs), 6) if costs else None,
        "per_task_cost_sources": sources,
        "runs": len(log),
        "unfinished_runs": sum(1 for e in log if "billed_usd" not in e),
        "note": "total_billed_usd = OpenRouter key usage delta over the run(s); includes any other use of the key meanwhile.",
    }


def cache_summary(trials, call_log):
    hit = sum(t.get("cache_hit_tokens") or 0 for t in trials.values())
    miss = sum(t.get("cache_miss_tokens") or 0 for t in trials.values())
    providers = {}
    for c in call_log:
        p = providers.setdefault(c["provider"] or "unknown", {"calls": 0, "cache_hit_tokens": 0, "prompt_tokens": 0})
        p["calls"] += 1
        p["cache_hit_tokens"] += c["cache_hit_tokens"]
        p["prompt_tokens"] += c["prompt_tokens"]
    for p in providers.values():
        p["cache_hit_rate"] = round(p["cache_hit_tokens"] / p["prompt_tokens"], 4) if p["prompt_tokens"] else None
    return {
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
        "cache_write_tokens": sum(t.get("cache_write_tokens") or 0 for t in trials.values()),
        "cache_hit_rate": round(hit / (hit + miss), 4) if hit + miss else None,
        "llm_calls": len(call_log),
        "calls_with_cache_hit": sum(1 for c in call_log if c["cache_hit_tokens"] > 0),
        "by_provider": providers,
    }


def main(out):
    pricing_file = read_json(out / "pricing.json")
    pricing = pricing_file["usd_per_token"] if pricing_file else {}
    call_log = []
    agent = load_trials(out / "agent", pricing, call_log)
    regrade = load_trials(out / "regrade") if (out / "regrade").is_dir() else {}

    summary = {"experiment": out.name, "agent_phase": score(agent)}
    if regrade:
        summary["regrade"] = score(regrade)
    summary["headline"] = summary["regrade" if regrade else "agent_phase"]
    if pricing_file:
        summary["cost"] = cost_summary(out, agent)
        summary["cache"] = cache_summary(agent, call_log)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    cols = ["cost_usd", "cost_source", "openrouter_reported_usd", "list_price_estimate_usd", "agent_reported_usd",
            "n_llm_calls", "input_tokens", "output_tokens", "cache_hit_tokens", "cache_miss_tokens",
            "cache_write_tokens", "cache_hit_rate", "calls_with_cache_hit"]
    with open(out / "per_task.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task", "agent_reward", "regrade_reward", "agent_error", "regrade_error", *cols])
        for task in sorted(set(agent) | set(regrade)):
            a, g = agent.get(task, {}), regrade.get(task, {})
            w.writerow([task, a.get("reward"), g.get("reward"), a.get("error"), g.get("error"),
                        *(a.get(c) for c in cols)])
    if call_log:
        with open(out / "calls.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CALL_COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(call_log)

    if pricing_file:
        print(f"\nPer-task cost and caching ({pricing_file['model']}):")
        print(f"  {'task':<50} {'cost_usd':>9}  {'source':<20} {'calls':>5} {'hit_rate':>8} {'hit_calls':>9} {'resolved':>8}")
        for task in sorted(agent):
            a = agent[task]
            res = regrade.get(task, a).get("reward")
            cost = f"{a['cost_usd']:.4f}" if a["cost_usd"] is not None else "n/a"
            rate = f"{a['cache_hit_rate']:.1%}" if a.get("cache_hit_rate") is not None else "n/a"
            hits = f"{a['calls_with_cache_hit']}/{a['n_llm_calls']}" if a.get("calls_with_cache_hit") is not None else "n/a"
            print(f"  {task[:50]:<50} {cost:>9}  {a['cost_source'] or '-':<20} {a['n_llm_calls'] or 0:>5}"
                  f" {rate:>8} {hits:>9} {res if res is not None else '-':>8}")
    h = summary["headline"]
    print(f"\n{out.name}: {h['resolved']}/{h['n_trials']} resolved"
          f" ({'re-graded' if regrade else 'agent phase'}), errors={h['errors']}")
    if pricing_file:
        c, k = summary["cost"], summary["cache"]
        fmt = lambda v: f"${v:.4f}" if v is not None else "n/a"  # noqa: E731
        if k["cache_hit_rate"] is not None:
            print(f"CACHE: {k['cache_hit_tokens']:,} hit / {k['cache_miss_tokens']:,} miss input tokens"
                  f" ({k['cache_hit_rate']:.1%} hit rate)"
                  + (f", {k['calls_with_cache_hit']}/{k['llm_calls']} calls hit the cache" if k["llm_calls"] else ""))
        print(f"TOTAL COST: {fmt(c['total_billed_usd'])} billed by OpenRouter"
              f"  (sum of per-task: {fmt(c['sum_of_per_task_usd'])}, mean/task: {fmt(c['mean_per_task_usd'])})")
        if c["unfinished_runs"]:
            print(f"  note: {c['unfinished_runs']} run(s) have no closing usage snapshot; billed total is incomplete")
    print(f"wrote {out / 'summary.json'}, {out / 'per_task.csv'}" + (f", {out / 'calls.csv'}" if call_log else ""))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
