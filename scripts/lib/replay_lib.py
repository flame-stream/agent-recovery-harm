#!/usr/bin/env python3
"""Replay harness for AppWorld episodes. Run from APPWORLD_ROOT (= replay_root)."""
import json, os, re, shutil, sys, pathlib, hashlib, collections

NORM = lambda s: re.sub(r'\s+', ' ', (s or "")).strip()


def db_snapshot(exp_name, task_id):
    """Read the DB diff files the environment writes after every execute()."""
    d = pathlib.Path("experiments/outputs") / exp_name / "tasks" / task_id / "dbs"
    out = {}
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.jsonl")):
        rows = []
        for line in open(f):
            line = line.strip()
            if line:
                rows.append(line)
        if rows:
            out[f.stem] = rows
    return out


def api_calls_snapshot(exp_name, task_id):
    f = pathlib.Path("experiments/outputs") / exp_name / "tasks" / task_id / "logs" / "api_calls.jsonl"
    if not f.exists():
        return []
    return [l.strip() for l in open(f) if l.strip()]


def snapshot_diff(before, after):
    """New SQL statements present in `after` but not in `before`, per app."""
    diff = {}
    for app, rows in after.items():
        b = collections.Counter(before.get(app, []))
        add = []
        for r in rows:
            if b[r]:
                b[r] -= 1
            else:
                add.append(r)
        if add:
            diff[app] = add
    return diff


def summarise_diff(diff):
    """-> list of (app, verb, table, n)"""
    out = []
    for app, rows in diff.items():
        c = collections.Counter()
        for r in rows:
            try:
                sql = json.loads(r)[0]
            except Exception:
                continue
            m = re.match(r'^(INSERT INTO|UPDATE|DELETE FROM)\s+(\w+)', sql or "", re.I)
            if m:
                c[(m.group(1).split()[0].upper(), m.group(2))] += 1
        for (verb, table), n in sorted(c.items()):
            out.append(dict(app=app, verb=verb, table=table, n=n))
    return out


def replay(task_id, codes, exp_name, stop_indices):
    """Execute `codes` in order. Returns per-block outputs and DB snapshots taken
    after each index listed in stop_indices (0-based)."""
    from appworld import AppWorld
    out_dir = pathlib.Path("experiments/outputs") / exp_name
    if out_dir.exists():
        shutil.rmtree(out_dir)
    results = dict(outputs=[], snapshots={}, error="")
    world = None
    try:
        world = AppWorld(task_id=task_id, experiment_name=exp_name,
                         max_interactions=len(codes) + 5,
                         max_api_calls_per_interaction=1000,
                         raise_on_failure=True, timeout_seconds=100)
        for i, code in enumerate(codes):
            try:
                msg = world.execute(code)
            except Exception as e:
                msg = f"__REPLAY_ERROR__ {type(e).__name__}: {e}"
                results["outputs"].append(msg)
                results["error"] = msg[:200]
                break
            results["outputs"].append(msg)
            if i in stop_indices:
                results["snapshots"][i] = db_snapshot(exp_name, task_id)
                results.setdefault("api_calls", {})[i] = api_calls_snapshot(exp_name, task_id)
    except Exception as e:
        results["error"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        try:
            if world is not None:
                world.close()
        except Exception:
            pass
    return results
