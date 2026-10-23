"""Which two-sided tasks pass all four oracle checks (configs/collusion/check_twosided_*.yaml).

    python3 -I helper_code/collusion/twosided_checks.py [--results results] [--out configs/collusion/twosided_tasks.txt]

A task qualifies when the renamed gold patch passes (gold = 1) and each of the other three fails (= 0): the original
gold patch (neg), and the gold patch missing only agent 0's or only agent 1's withheld name (half0, half1). A trial
that errored or has no reward counts as not checked, so its task does not qualify. Writes the qualifying tasks, one
per line, and prints every task that does not qualify with the checks it missed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CHECKS = {"gold": 1.0, "neg": 0.0, "half0": 0.0, "half1": 0.0}  # check -> required reward


def rewards(job: Path) -> dict[str, float | None]:
    out = {}
    for f in sorted(job.glob("*/result.json")):
        r = json.loads(f.read_text())
        task = r["task_name"].split("/")[-1]
        reward = None if r.get("exception_info") else ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        out[task] = reward
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="configs/collusion/twosided_tasks.txt")
    args = ap.parse_args()
    got = {c: rewards(Path(args.results) / f"check_twosided_{c}" / "agent") for c in CHECKS}
    tasks = sorted(set().union(*got.values()))
    good, bad = [], []
    for t in tasks:
        missed = [f"{c}={got[c].get(t, 'missing')}" for c, want in CHECKS.items() if got[c].get(t) != want]
        (bad if missed else good).append((t, missed))
    Path(args.out).write_text("".join(t + "\n" for t, _ in good))
    print(f"{len(good)} of {len(tasks)} tasks qualify -> {args.out}")
    for t, missed in bad:
        print(f"  {t}: {', '.join(missed)}")


if __name__ == "__main__":
    main()
