#!/usr/bin/env python3
"""Step 3a: does world.evaluate() return success on a known-good full solution?

test_challenge ships no solution code, so the reference full solution is a historical
trajectory that the official evaluation marked successful. It is replayed block by
block in a fresh world on the matching stand and evaluated exactly as pilot_run.py does.
Negative control: the pilot's own source trajectory for the same task (officially failed).

Usage: STAND=<stand dir> PROJ=<project> python evaluator_check.py <task_id> <task_dir> <label>
Appends one JSON line to evaluator_check.jsonl.
"""
import json, os, pathlib, sys

PROJ = pathlib.Path(os.environ["PROJ"]).resolve()
STAND = pathlib.Path(os.environ["STAND"]).resolve()
sys.path.insert(0, str(PROJ / "replay_root"))
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)
import appworld_audit as A
import instrument as I

FREEZE = I.verify_freeze()
task_id, task_dir, label = sys.argv[1], (PROJ / sys.argv[2]).resolve(), sys.argv[3]
blocks = A.parse_blocks(task_dir / "logs" / "environment_io.md")
os.chdir(STAND)
from appworld import AppWorld

res = dict(task_id=task_id, label=label, source=sys.argv[2], n_blocks=len(blocks),
           stand=STAND.name, freeze=FREEZE)
world = AppWorld(task_id=task_id, experiment_name=f"evalcheck_{label}_{task_id}")
try:
    failed = 0
    for b in blocks:
        out = world.execute(b["code"])
        failed += int("Execution failed" in (out or ""))
    res["blocks_failed"] = failed
    res["task_completed"] = bool(world.task_completed())
    ev = world.evaluate()
    res["success"] = bool(ev.success)
    try:
        d = ev.to_dict()
        res["passes"] = len(d.get("passes", []))
        res["failures"] = [f.get("requirement", "")[:160] for f in d.get("failures", [])][:5]
    except Exception as ex:
        res["detail_error"] = f"{type(ex).__name__}: {ex}"[:160]
finally:
    world.close()
os.chdir(PROJ)
with open(PROJ / "reports/pilot_closeout" / "evaluator_check.jsonl", "a") as f:
    f.write(json.dumps(res, ensure_ascii=False) + "\n")
print(json.dumps(res, ensure_ascii=False))
