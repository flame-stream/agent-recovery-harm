#!/usr/bin/env python3
"""Counterfactual step 0: capture the early calls (prefix + studied block) of every pilot
continuation by re-executing exactly the code pilot_run.py executed before the
continuation. No model is called.

pilot_run.py order (reproduced here):
  AppWorld(task) -> Recorder.enable() -> prefix blocks 0..fi-1 -> condition preamble
  -> snap A -> studied block (A: original, B/C/E: labelled_blocks.json, D:
  reference_blocks.json) -> snap B
The pilot recorder was armed only during the continuation, so these calls were never
logged with responses. Here a thin pass-through hook on Requester.request logs every call
(phase, api, args without access_token, error) and does not take per-call snapshots.

Two controls per continuation, both must pass, otherwise replay_mismatch:
  1. snapshot B after the replay == saved B in pilot_out|pilot_E/snap_<key>.json
     (same Recorder.snap, i.e. world.save_state(format="full") of the episode's app)
  2. the replay's own logs/api_calls.jsonl (written by AppWorld, same format as the
     historical one) == the first N lines of the historical api_calls.jsonl of the source
     run, compared on (method, url, data without access_token).
  plus: the studied block fails (or not) exactly as in the original environment_io.md,
  with the same final exception line (ctl_fail).
Nothing is adjusted by hand: a mismatch is recorded with its first differing position.

Output: reports/counterfactual/early_calls/<COND>__<task>__<block>.jsonl (one call per
line), controls in reports/counterfactual/early_calls/_controls_<DATAVER>.json.
Env: PROJ, STAND, APPWORLD_DATA, DATAVER, CONDS (e.g. "ABCDE").
"""
import csv, json, os, pathlib, sys, traceback

os.environ.setdefault("COND", "A")
import pilot_run as P                      # verify_freeze() runs on import
import appworld_audit as A
import instrument as I
import effects_runtime as E
import effects_runtime_e as EE

PROJ, STAND, DV = P.PROJ, P.STAND, os.environ["DATAVER"]
OUT = PROJ / "reports" / "counterfactual" / "early_calls"
OUT.mkdir(parents=True, exist_ok=True)


def norm_hist(line):
    d = json.loads(line)
    data = {k: v for k, v in (d.get("data") or {}).items() if k != "access_token"}
    return [d.get("method"), d.get("url"), data]


def usable_keys(cond):
    f = (PROJ / "pilot_E" / f"pilot_results_E_{DV}.json") if cond == "E" else \
        (PROJ / f"pilot_results_{cond}_{DV}.json")
    return {r["episode_id"] for r in json.load(open(f)) if r.get("usable")} if f.exists() else set()


def capture(cond, ep):
    P.COND = cond
    key = f"{cond}__{ep['task_id']}__{ep['block']}"
    td = (PROJ / ep["path"]).resolve()
    blocks = A.parse_blocks(td / "logs" / "environment_io.md")
    fi = {b["index"]: i for i, b in enumerate(blocks)}[int(ep["block"])]
    study, mode = P.variant_block(ep, blocks[fi]["code"])
    apis_for_snap = sorted({(ep["api"] or "amazon.x").split(".")[0]})
    exp = f"cfcap_{cond}_{ep['task_id']}_{ep['block']}"
    res = dict(key=key, episode_id=ep["episode_id"], condition=cond, data_version=DV)
    os.chdir(STAND)
    from appworld import AppWorld
    from appworld.requester import Requester
    world = None
    calls, phase = [], ["prefix"]
    try:
        world = AppWorld(task_id=ep["task_id"], experiment_name=exp)
        rec = I.Recorder(world, apis_for_snap, STAND / "pilot_work" / f"cf_{cond}_{ep['block']}",
                         watch=lambda a, n: True)
        rec.enable()                                   # armed=False: pass-through, as in the pilot
        inner = Requester.request

        def logged(self_r, _app_name, _api_name, *a, **data):
            err = None
            try:
                return inner(self_r, _app_name, _api_name, *a, **data)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:300]
                raise
            finally:
                calls.append(dict(i=len(calls), phase=phase[0], api=f"{_app_name}.{_api_name}",
                                  args={k: v for k, v in data.items() if k not in
                                        ("access_token", "client", "raise_on_failure", "show", "track")},
                                  ok=err is None, error=err))
        Requester.request = logged
        for i in range(fi):
            world.execute(blocks[i]["code"])
        phase[0] = "preamble"
        if mode == "strict":
            world.execute(EE.preamble())
        elif mode:
            world.execute(E.preamble(mode))
        A_state, mA = rec.snap("A")
        phase[0] = "block"
        out0 = world.execute(study)
        B_state, mB = rec.snap("B")
        Requester.request = inner
        rec.disable()
        res["block_failed"] = int("Execution failed" in (out0 or ""))
        orig_out = blocks[fi].get("output") or ""
        res["orig_block_failed"] = int("Execution failed" in orig_out or "Traceback" in orig_out)
        last = lambda o: next((l.strip() for l in reversed((o or "").splitlines())
                               if l.strip().startswith(("Exception", "Error", "{"))), "")
        res["block_exc"], res["orig_exc"] = last(E.clean_traceback(out0))[:200], last(orig_out)[:200]
        res["ctl_fail"] = int(res["block_failed"] == res["orig_block_failed"] and
                              (not res["block_failed"] or res["block_exc"] == res["orig_exc"]))
        bc = [c for c in calls if c["phase"] == "block"]
        res["block_last_call"] = bc[-1]["api"] if bc else None
        res["block_last_call_ok"] = bc[-1]["ok"] if bc else None
        res["n_calls"] = len(calls)
        res["n_block_calls"] = len(bc)
        # control 1: snapshot B
        sdir = PROJ / ("pilot_E" if cond == "E" else "pilot_out")
        saved = json.load(open(sdir / f"snap_{key}.json"))["B"]
        same = saved == B_state
        res["ctl_snapB"] = int(same)
        if not same:
            diff = sorted(t for t in set(saved) | set(B_state) if saved.get(t) != B_state.get(t))
            res["ctl_snapB_tables"] = diff[:10]
        # control 2: historical api_calls.jsonl
        world.close()
        world = None
        mine_p = STAND / "experiments" / "outputs" / exp / "tasks" / ep["task_id"] / "logs" / "api_calls.jsonl"
        mine = [norm_hist(l) for l in open(mine_p) if l.strip()]
        hist = [norm_hist(l) for l in open(td / "logs" / "api_calls.jsonl") if l.strip()]
        first = next((n for n, (x, y) in enumerate(zip(mine, hist)) if x != y), None)
        if first is None and len(mine) > len(hist):
            first = len(hist)
        res["n_replay_http"] = len(mine)
        res["ctl_hist"] = int(first is None)
        if first is not None:
            res["ctl_hist_first_diff"] = dict(pos=first, replay=mine[first] if first < len(mine) else None,
                                              hist=hist[first] if first < len(hist) else None)
        res["n_recorded_vs_http"] = [len(calls), len(mine)]
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"[:300]
        res["trace"] = traceback.format_exc()[-600:]
        res["ctl_snapB"] = res.get("ctl_snapB", 0)
        res["ctl_hist"] = res.get("ctl_hist", 0)
    finally:
        try:
            from appworld.requester import Requester as R2
            if R2.request is not inner:
                R2.request = inner
        except Exception:
            pass
        try:
            if world is not None:
                world.close()
        except Exception:
            pass
        os.chdir(PROJ)
    res["replay_mismatch"] = int(not (res.get("ctl_snapB") and res.get("ctl_hist") and res.get("ctl_fail")))
    with open(OUT / f"{key}.jsonl", "w") as f:
        for c in calls:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return res


def main():
    conds = os.environ.get("CONDS", "ABCDE")
    eps = [r for r in csv.DictReader(open(PROJ / "episodes.csv")) if r["data_version"] == DV]
    cp = OUT / f"_controls_{DV}.json"
    done = {r["key"]: r for r in json.load(open(cp))} if cp.exists() else {}
    for cond in conds:
        ok = usable_keys(cond)
        for ep in eps:
            key = f"{cond}__{ep['task_id']}__{ep['block']}"
            if ep["episode_id"] not in ok or key in done or (os.environ.get("ONLY") and os.environ["ONLY"] not in key):
                continue
            r = capture(cond, ep)
            done[key] = r
            json.dump(list(done.values()), open(cp, "w"), ensure_ascii=False, indent=1)
            print(f"[{key}] calls={r.get('n_calls')} block={r.get('n_block_calls')} failed={r.get('block_failed')} "
                  f"snapB={r.get('ctl_snapB')} hist={r.get('ctl_hist')} fail={r.get('ctl_fail')} {r.get('error', '')[:80]}", flush=True)


if __name__ == "__main__":
    main()
