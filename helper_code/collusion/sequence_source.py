"""Lay out a sequences run's per-task patches as a source job for patch_replay, and print the tasks it covers.

    python3 -I helper_code/collusion/sequence_source.py results/<name>

A sequences trial (collusion_group ``sequences``) works through several tasks but is one Harbor trial, so
patch_replay (which looks up ``<source_job>/*/result.json`` by task name) cannot find tasks 2.. in it. This writes
``results/<name>/seq_source/<trial>__t<k>/`` with ``result.json`` ({"task_name": ...}) and
``agent/agent_<i>/model.patch`` (from ``agent_<i>/task_<k>/model.patch``) for every task of every trial, then prints
one task name per line for the re-grade's ``-i`` flags.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def main(out: Path) -> None:
    src = out / "seq_source"
    tasks: list[str] = []
    for trial in sorted(p for p in (out / "agent").iterdir() if (p / "agent" / "group.json").is_file()):
        agent_dir = trial / "agent"
        for tdir in sorted(agent_dir.glob("agent_*/task_*"), key=lambda p: (p.parent.name, int(p.name[5:]))):
            k = tdir.name.removeprefix("task_")
            task = json.loads((tdir / "result.json").read_text())["task"]
            dest = src / f"{trial.name}__t{k}"
            (dest / "agent" / tdir.parent.name).mkdir(parents=True, exist_ok=True)
            (dest / "result.json").write_text(json.dumps({"task_name": task}))
            shutil.copy2(tdir / "model.patch", dest / "agent" / tdir.parent.name / "model.patch")
            if task not in tasks:
                tasks.append(task)
    print("\n".join(tasks))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
