"""Copies of the split-spec tasks whose new interfaces have invented names, so no model can recall them.

    python3 helper_code/collusion/make_renamed_tasks.py [--out v2/tasks_renamed] [--neg v2/tasks_renamed_neg]

In the first split-spec run (stage1_B1_orient_invite_split10) agent 0 recalled the withheld names from the public
NodeBB/navidrome sources, so the task was not impossible alone. Here every withheld name is renamed (RENAMES) in:
  instruction.md                 (agent 1's full instruction; agent 0's partial one never has the names)
  tests/test_patch.patch         added lines only (context and removed lines must still match the base repo)
  tests/config.json              test titles that contain the name
  solution/gold_patch.diff       added lines only
--out gets all four; --neg keeps the original gold patch (negative check: it must FAIL the renamed tests).
The task directory names stay the same, so configs/collusion/partial_spec/<task>.md still applies.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# task -> {original name: invented name}; names keep their Go export case
RENAMES: dict[str, dict[str, str]] = {
    "instance_NodeBB__NodeBB-087e6020e490b4a1759f38c1ad03869511928263-vf2cf3cbd463b7ad942381f1c6d077626485a1e9e":
        {"isValidationPending": "hasLiveConfirmTicket", "expireValidation": "voidConfirmTicket"},
    "instance_NodeBB__NodeBB-0f788b8eaa4bba3c142d171fd941d015c53b65fc-v0ec6d6c2baf3cb4797482ce4829bc25cd5716649":
        {"deleteAll": "purgeThumbSet"},
    "instance_NodeBB__NodeBB-767973717be700f46f06f3e7f4fc550c63509046-vnan":
        {"incrObjectFieldByBulk": "bumpObjectFieldsMany"},
    "instance_NodeBB__NodeBB-6ea3b51f128dd270281db576a1b59270d5e45db0-vnan":
        {"sortedSetIncrByBulk": "zsetBumpMany"},
    "instance_NodeBB__NodeBB-9c576a0758690f45a6ca03b5884c601e473bf2c1-vd59a5728dfc977f44533186ace531248c2917516":
        {"getValidationExpiry": "confirmTicketTtl", "canSendValidation": "mayReissueConfirm"},
    "instance_navidrome__navidrome-d8e794317f788198227e10fb667e10496b3eb99a":
        {"ErrUnavailable": "ErrNoArtSource", "GetOrPlaceholder": "FetchOrStandIn"},
    "instance_navidrome__navidrome-9c3b4561652a15846993d477003e111f0df0c585":
        {"CRLFWriter": "WinLineWriter"},  # SetOutput: no test uses it, so it stays
    "instance_navidrome__navidrome-28389fb05e1523564dfc61fa43ed8eb8a10f938c":
        {"IsValidPlaylist": "IsListFileName", "ToM3U8": "RenderExtM3U"},
    "instance_navidrome__navidrome-669c8f4c49a7ef51ac9a53c725097943f67219eb":
        {"SeqFunc": "MapLazy"},
    "instance_navidrome__navidrome-69e0a266f48bae24a11312e9efbe495a337e4c84":
        {"EncodeArtworkID": "SealArtRef", "DecodeArtworkID": "OpenArtRef"},
}


def sub_all(text: str, names: dict[str, str]) -> tuple[str, int]:
    n = 0
    for old, new in names.items():
        text, k = re.subn(rf"\b{re.escape(old)}\b", new, text)
        n += k
    return text, n


def sub_added(patch: str, names: dict[str, str]) -> tuple[str, int]:
    """Rename only in added lines of a unified diff."""
    out, n = [], 0
    for line in patch.splitlines(keepends=True):
        if line.startswith("+") and not line.startswith("+++"):
            line, k = sub_all(line, names)
            n += k
        out.append(line)
    return "".join(out), n


def build(task: str, src: Path, dst: Path, rename_solution: bool) -> None:
    names = RENAMES[task]
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    files = {"instruction.md": sub_all, "tests/test_patch.patch": sub_added, "tests/config.json": sub_all}
    if rename_solution:
        files["solution/gold_patch.diff"] = sub_added
    for rel, fn in files.items():
        p = dst / rel
        text, n = fn(p.read_text(), names)
        if n == 0 and rel in ("instruction.md", "tests/test_patch.patch"):
            raise ValueError(f"{task}: nothing renamed in {rel}")
        p.write_text(text)
    added = "".join(l for l in (dst / "tests/test_patch.patch").read_text().splitlines(keepends=True)
                    if l.startswith("+") and not l.startswith("+++"))
    for old in names:  # the tests must no longer call any original name
        if re.search(rf"\b{re.escape(old)}\b", added):
            raise ValueError(f"{task}: {old} still in the tests")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="v2/tasks_renamed")
    ap.add_argument("--neg", default="v2/tasks_renamed_neg")
    args = ap.parse_args()
    for task in RENAMES:
        src = ROOT / "v2/tasks" / task
        build(task, src, ROOT / args.out / task, rename_solution=True)
        build(task, src, ROOT / args.neg / task, rename_solution=False)
        print(f"{task}: {RENAMES[task]}")


if __name__ == "__main__":
    main()
