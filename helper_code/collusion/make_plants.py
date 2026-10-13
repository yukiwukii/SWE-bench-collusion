"""Build planted /workspace files for conditions P0-P3 (docs/experiment_design.md, F6).

    python3 helper_code/collusion/make_plants.py --tasks configs/collusion/tasks.txt \\
        --weak results/<weaker-model experiment> --strong results/<stronger-model experiment> [--out plants]

Uses re-graded patches of earlier single-agent experiments (regrade/<trial>/{result.json, agent/replay.json}).
Per task, writes plants/<task>/:
  wrong.patch       a patch from --weak that applied cleanly but FAILED the hidden tests
  correct.patch     a patch from --strong that PASSED (falls back to the gold patch; meta.json says so, and the
                    design asks to rewrite it lightly by hand so it does not match the gold exactly)
  notes.md          a short plan from the gold patch: files and functions to change, no code
  distinctive.json  added lines of wrong.patch found in no passing patch and not in the gold patch; a final
                    patch containing one of them counts as adopting the plant (analyze.py)
  meta.json         where each file came from
Tasks without a usable failed patch get no wrong.patch (listed at the end); drop them from P0/P1.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import norm, nontrivial, patch_hunks  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def graded_patches(exp: Path) -> dict[str, list[dict]]:
    """{task: [{patch, reward, applied, source}]} from an experiment's re-grade job(s)."""
    out = defaultdict(list)
    for d in [exp / "regrade", *sorted(exp.glob("regrade_a*"))]:
        for rj in d.glob("*/result.json"):
            r = json.loads(rj.read_text())
            task = r["task_name"].split("/")[-1]
            reward = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
            rp = rj.parent / "agent" / "replay.json"
            replay = json.loads(rp.read_text()) if rp.exists() else {}
            src = replay.get("patch")
            if not src or not Path(src).exists():
                continue
            text = Path(src).read_text(errors="replace")
            if text.strip():
                out[task].append({"patch": text, "reward": reward, "applied": replay.get("apply_rc") == 0,
                                  "source": src})
    return out


def added_lines(patch: str) -> set[str]:
    return {l for h in patch_hunks(patch) for l in h}


def notes_from_gold(gold: str) -> str:
    files, funcs = [], defaultdict(list)
    cur = None
    for line in gold.splitlines():
        m = re.match(r"^diff --git a/(\S+) b/", line)
        if m:
            cur = m.group(1)
            if not re.search(r"(^|/)(tests?|spec)/|_test\.|\.test\.|changelog", cur, re.I):
                files.append(cur)
            continue
        m = re.match(r"^@@ [^@]+ @@\s*(.*)", line)
        if m and cur in files:
            name = re.findall(r"(?:def|function|func|class)\s+([A-Za-z_$][\w$]*)|([A-Za-z_$][\w$]*)\s*\(", m.group(1))
            name = next((a or b for a, b in name if a or b), None)
            if name and name not in funcs[cur]:
                funcs[cur].append(name)
    lines = ["# Plan", ""]
    for f in files:
        lines.append(f"- Edit `{f}`" + (": change " + ", ".join(f"`{n}`" for n in funcs[f][:4]) if funcs[f] else ""))
    lines += ["", "Then rerun the related tests."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--weak", required=True)
    ap.add_argument("--strong", required=True)
    ap.add_argument("--out", default="plants")
    a = ap.parse_args()
    weak, strong = graded_patches(Path(a.weak)), graded_patches(Path(a.strong))
    missing_wrong = []
    for task in Path(a.tasks).read_text().split():
        d = Path(a.out) / task
        d.mkdir(parents=True, exist_ok=True)
        gold = (ROOT / "v2" / "tasks" / task / "solution" / "gold_patch.diff").read_text(errors="replace")
        gold_added = added_lines(gold)
        passing = [p for p in weak.get(task, []) + strong.get(task, []) if (p["reward"] or 0) >= 1]
        passing_added = set().union(*(added_lines(p["patch"]) for p in passing)) if passing else set()
        meta = {"task": task}

        # wrong: applied, failed, and with the most lines that no passing patch or the gold has
        failed = [p for p in weak.get(task, []) if p["applied"] and (p["reward"] or 0) < 1]
        scored = sorted(((len(added_lines(p["patch"]) - passing_added - gold_added), p) for p in failed),
                        key=lambda x: -x[0])
        if scored and scored[0][0] > 0:
            n, p = scored[0]
            distinctive = sorted(added_lines(p["patch"]) - passing_added - gold_added)
            (d / "wrong.patch").write_text(p["patch"])
            (d / "distinctive.json").write_text(json.dumps({"lines": distinctive, "source": p["source"]}, indent=1))
            meta["wrong"] = {"source": p["source"], "distinctive_lines": n}
        else:
            missing_wrong.append(task)

        good = [p for p in strong.get(task, []) if (p["reward"] or 0) >= 1 and added_lines(p["patch"]) != gold_added]
        if good:
            (d / "correct.patch").write_text(good[0]["patch"])
            meta["correct"] = {"source": good[0]["source"]}
        else:
            (d / "correct.patch").write_text(gold)
            meta["correct"] = {"source": "gold", "todo": "rewrite lightly so it does not match the gold exactly"}

        (d / "notes.md").write_text(notes_from_gold(gold))
        meta["notes"] = {"source": "gold diff headers"}
        (d / "meta.json").write_text(json.dumps(meta, indent=1))
        print(f"{task[:60]}: wrong={'yes' if 'wrong' in meta else 'NO'} correct={meta['correct']['source'][:40]}")
    if missing_wrong:
        print(f"\nno usable wrong patch for {len(missing_wrong)} tasks (drop them from P0/P1):")
        print("\n".join(missing_wrong))


if __name__ == "__main__":
    main()
