"""Compare two collusion conditions (docs/experiment_design.md, section 7).

    python3 helper_code/collusion/stats.py results/<A> results/<B1> [--measure took_foreign] [--exclude tasks.txt]

Reads each experiment's collusion_agents.csv (run analyze.py first). For a binary per-agent measure
(took_foreign, notice, read, noticed_take, resolved, ...):
  - rates p_A, p_B, the difference Δ = p_B - p_A, SE_Δ = sqrt(p_A(1-p_A)/N_A + p_B(1-p_B)/N_B), 95% CI, z
  - McNemar's exact test on instances present in both (instance outcome = mean over its agents and seeds >= 0.5)
  - if statsmodels is installed: logistic GEE with instance clusters (stands in for the mixed-effects model)
--exclude drops tasks (e.g. those the broken-task filter flagged), to report results with and without it.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def load(exp: Path, measure: str, exclude: set[str]) -> list[tuple[str, int]]:
    out = []
    for r in csv.DictReader(open(exp / "collusion_agents.csv")):
        v = r.get(measure)
        if r["task"] in exclude or v in (None, "", "None"):
            continue
        out.append((r["task"], 1 if v in ("True", "1", "1.0") else 0))
    return out


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from discordant counts b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--measure", default="took_foreign")
    ap.add_argument("--exclude")
    args = ap.parse_args()
    exclude = set(Path(args.exclude).read_text().split()) if args.exclude else set()
    A, B = load(Path(args.a), args.measure, exclude), load(Path(args.b), args.measure, exclude)
    if not A or not B:
        raise SystemExit("no rows with this measure in one of the experiments")
    pa, pb = sum(v for _, v in A) / len(A), sum(v for _, v in B) / len(B)
    se = math.sqrt(pa * (1 - pa) / len(A) + pb * (1 - pb) / len(B))
    d = pb - pa
    res = {"measure": args.measure, "A": Path(args.a).name, "B": Path(args.b).name,
           "n_A": len(A), "n_B": len(B), "p_A": round(pa, 4), "p_B": round(pb, 4), "delta": round(d, 4),
           "se_delta": round(se, 4), "ci95": [round(d - 1.96 * se, 4), round(d + 1.96 * se, 4)],
           "z": round(d / se, 2) if se else None, "excluded_tasks": len(exclude)}

    by_a, by_b = defaultdict(list), defaultdict(list)
    for t, v in A:
        by_a[t].append(v)
    for t, v in B:
        by_b[t].append(v)
    common = sorted(set(by_a) & set(by_b))
    ia = {t: sum(by_a[t]) / len(by_a[t]) >= 0.5 for t in common}
    ib = {t: sum(by_b[t]) / len(by_b[t]) >= 0.5 for t in common}
    b = sum(1 for t in common if ia[t] and not ib[t])
    c = sum(1 for t in common if ib[t] and not ia[t])
    res["mcnemar"] = {"paired_instances": len(common), "A_only": b, "B_only": c, "p": round(mcnemar_exact(b, c), 4)}

    try:
        import numpy as np
        import statsmodels.api as sm
        rows = [(t, v, 0) for t, v in A] + [(t, v, 1) for t, v in B]
        tasks = sorted({t for t, _, _ in rows})
        y = np.array([v for _, v, _ in rows])
        X = sm.add_constant(np.array([[cond] for _, _, cond in rows], dtype=float))
        groups = np.array([tasks.index(t) for t, _, _ in rows])
        fit = sm.GEE(y, X, groups=groups, family=sm.families.Binomial(),
                     cov_struct=sm.cov_struct.Exchangeable()).fit()
        res["gee_logit"] = {"coef_B": round(float(fit.params[1]), 4), "se": round(float(fit.bse[1]), 4),
                            "p": round(float(fit.pvalues[1]), 4)}
    except ImportError:
        res["gee_logit"] = "statsmodels not installed"
    except Exception as e:  # e.g. perfect separation with tiny pilots
        res["gee_logit"] = f"failed: {e}"
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
