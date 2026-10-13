"""Pick instances for the collusion experiment.

Stage 1 (no screening run yet): a seeded random sample from repos with small images, skipping HARD-51 tasks
(too hard to leave anything worth copying) and images above a compressed size cap (local docker disk)::

    python3 helper_code/collusion/select_instances.py sample --n 10 --repos ansible NodeBB navidrome \\
        --max-image-gb 1.5 --out configs/collusion/stage1_tasks.txt

From a screening experiment (a single-agent config run with n_attempts = k on the candidates): keep tasks
whose re-graded solve rate is within [lo, hi], and pair each with a task from a different repo (for the
different-instance conditions C and P0)::

    python3 helper_code/collusion/select_instances.py screen results/<screen> --lo 0.2 --hi 0.6 \\
        --n 30 --out configs/collusion/tasks.txt --pairs configs/collusion/pairs.json
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "ghcr.io/scaleapi/swe-bench_pro-v2:{}"


def repo(task: str) -> str:
    return task.removeprefix("instance_").split("__")[0]


def image_gb(task: str) -> float | None:
    """Compressed size of the task's linux/amd64 image (sum of layers), from the registry; None if unavailable.
    Some tags are a single manifest, others an index (amd64 image + attestation entry)."""
    r = subprocess.run(["docker", "manifest", "inspect", "--verbose", IMAGE.format(task)], capture_output=True,
                       text=True, timeout=60)
    try:
        entries = json.loads(r.stdout)
    except ValueError:
        return None
    for e in entries if isinstance(entries, list) else [entries]:
        if (e.get("Descriptor", {}).get("platform") or {}).get("architecture", "amd64") == "amd64":
            m = e.get("SchemaV2Manifest") or e.get("OCIManifest") or {}
            if m.get("layers"):
                return sum(l["size"] for l in m["layers"]) / 1e9
    return None


def write(tasks: list[str], out: Path) -> None:
    out.write_text("\n".join(tasks) + "\n")
    print(f"wrote {len(tasks)} tasks to {out}")
    print("task_names: [" + ", ".join(tasks) + "]")


def sample(a) -> None:
    hard = set((ROOT / "v2" / "hard51_ids.txt").read_text().split())
    tasks = sorted(p.name for p in (ROOT / "v2" / "tasks").iterdir() if p.is_dir())
    pool = [t for t in tasks if repo(t) in a.repos and t not in hard]
    random.Random(a.seed).shuffle(pool)
    per_repo = -(-a.n // len(a.repos))  # spread over repos
    picked, count = [], defaultdict(int)
    for t in pool:
        if len(picked) == a.n:
            break
        if count[repo(t)] >= per_repo:
            continue
        gb = image_gb(t)
        if gb is None or gb > a.max_image_gb:
            print(f"skip {t[:60]} (image {gb if gb is None else round(gb, 2)} GB)")
            continue
        print(f"pick {t[:60]} ({gb:.2f} GB)")
        picked.append(t)
        count[repo(t)] += 1
    write(sorted(picked), Path(a.out))


def screen(a) -> None:
    exp = Path(a.experiment)
    rewards = defaultdict(list)
    for d in [exp / "regrade"] if (exp / "regrade").is_dir() else [exp / "agent"]:
        for rj in d.glob("*/result.json"):
            r = json.loads(rj.read_text())
            reward = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
            if reward is not None:
                rewards[r["task_name"].split("/")[-1]].append(reward >= 1)
    rates = {t: sum(v) / len(v) for t, v in rewards.items()}
    keep = sorted(t for t, r in rates.items() if a.lo <= r <= a.hi)
    print(f"{len(keep)}/{len(rates)} tasks with solve rate in [{a.lo}, {a.hi}]")
    random.Random(a.seed).shuffle(keep)
    keep = sorted(keep[:a.n])
    write(keep, Path(a.out))
    if a.pairs:  # partner: a kept task from another repo, each used once where possible
        pairs, used = {}, set()
        for t in keep:
            options = [u for u in keep if repo(u) != repo(t) and u not in used] or \
                      [u for u in keep if repo(u) != repo(t)]
            if options:
                pairs[t] = options[0]
                used.add(options[0])
        Path(a.pairs).write_text(json.dumps(pairs, indent=1) + "\n")
        print(f"wrote {len(pairs)} pairs to {a.pairs}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--n", type=int, default=10)
    s.add_argument("--repos", nargs="+", default=["ansible", "NodeBB", "navidrome"])
    s.add_argument("--max-image-gb", type=float, default=1.5)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=sample)
    c = sub.add_parser("screen")
    c.add_argument("experiment")
    c.add_argument("--lo", type=float, default=0.2)
    c.add_argument("--hi", type=float, default=0.6)
    c.add_argument("--n", type=int, default=30)
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--out", required=True)
    c.add_argument("--pairs")
    c.set_defaults(fn=screen)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
