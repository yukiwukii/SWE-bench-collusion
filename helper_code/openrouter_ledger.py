"""Record what OpenRouter actually billed for an experiment, by snapshotting the key's total usage.

    python3 helper_code/openrouter_ledger.py begin results/<name> <model_slug>
    python3 helper_code/openrouter_ledger.py end   results/<name>

begin: prints the key's remaining budget, saves the model's list prices to <dir>/pricing.json and opens an
entry in <dir>/cost_log.json. end: waits for OpenRouter's usage counter to settle and closes the entry with
the billed delta. One entry per run/resume; summarize_results.py sums them. Any other use of the same key
while the experiment runs is included in the delta.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "v2" / "tooling"))
from openrouter_pricing import key_status, model_pricing  # noqa: E402


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def begin(out, slug):
    s = key_status()
    remaining = s["limit_remaining_usd"]
    print(f"OpenRouter key: ${s['usage_usd']:.4f} used so far"
          + (f", ${remaining:.4f} of ${s['limit_usd']} {s['limit_reset'] or ''} limit remaining" if remaining is not None else ""))
    if remaining is not None and remaining <= 0:
        sys.exit("OpenRouter key limit reached; not starting.")
    pricing_file = out / "pricing.json"
    if not pricing_file.exists():
        pricing_file.write_text(json.dumps({"model": slug, "fetched_at": now(),
                                            "usd_per_token": model_pricing(slug)}, indent=2) + "\n")
    log = json.loads((out / "cost_log.json").read_text()) if (out / "cost_log.json").exists() else []
    if log and "usage_after_usd" not in log[-1]:  # previous run was killed before it could close its entry
        log[-1].update(finished_at=None, usage_after_usd=s["usage_usd"],
                       billed_usd=round(s["usage_usd"] - log[-1]["usage_before_usd"], 6), closed_late=True)
    log.append({"started_at": now(), "usage_before_usd": s["usage_usd"]})
    (out / "cost_log.json").write_text(json.dumps(log, indent=2) + "\n")


def end(out):
    log = json.loads((out / "cost_log.json").read_text())
    entry = log[-1]
    if "usage_after_usd" in entry:
        return
    # OpenRouter's counter can lag the last requests by 20+ s: wait, then require two equal readings 15 s apart.
    time.sleep(30)
    usage = key_status()["usage_usd"]
    for _ in range(10):
        time.sleep(15)
        settled, usage = usage, key_status()["usage_usd"]
        if usage == settled:
            break
    entry.update(finished_at=now(), usage_after_usd=usage,
                 billed_usd=round(usage - entry["usage_before_usd"], 6))
    (out / "cost_log.json").write_text(json.dumps(log, indent=2) + "\n")


if __name__ == "__main__":
    cmd, out = sys.argv[1], Path(sys.argv[2])
    begin(out, sys.argv[3]) if cmd == "begin" else end(out)
