#!/usr/bin/env python3
"""Main-sample counterfactual, step 1: capture every API call of a sampled episode
(prefix, failed block, continuation) with arguments and responses, by re-executing the
historical code of the episode exactly as replay_episode.py did for the damage audit.
No model is called.

Derived from capture_early_calls.py (pilot). Changes, marked:
  [main] episodes come from random_sample_{legacy,modern}.csv, not from the pilot; the
         code is the historical environment_io.md blocks (no labelled/reference variant,
         no condition preamble);
  [main] the logging hook is on from the FIRST call and the continuation is replayed too
         (phase = prefix | block | cont), because damage_out/call_diffs stores the
         continuation writes with strings > 60 chars cut to "<token>" and no reads;
  [main] snapshots A/B/C are taken with damage_lib.Recorder.snapshot (the machinery that
         produced damage_out/snapshots), not instrument.Recorder;
  [main] control 1 compares B with the stored damage_out/snapshots/<key>.json in the form
         it was stored (moving tables in full, static tables as row counts, big tables
         as A->B deltas); C is compared the same way as an extra control (not required).

Controls (replay_mismatch = not all of snapB, hist, fail -- the same criterion as the pilot):
  ctl_snapB  B after the replayed block == stored B
  ctl_hist   (method, url, data without access tokens) of the replay's own
             logs/api_calls.jsonl == the same positions of the historical api_calls.jsonl,
             over the prefix and the block
  ctl_fail   the block fails (or not) as in the historical environment_io.md, same last
             exception line
  extra, not in the criterion: ctl_snapC, ctl_hist_full (the whole trajectory)

Usage: capture_main.py '<episode json>'  -> prints RESULT {...}; writes
reports/counterfactual_main/early_calls_main/<key>.jsonl
"""
import collections, json, os, pathlib, sys, traceback

PROJ = pathlib.Path(os.environ["PROJ"]).resolve()
STAND = pathlib.Path(os.environ["STAND"]).resolve()
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)
import appworld_audit as A
import damage_lib as D

OUT = PROJ / "reports" / "counterfactual_main" / "early_calls_main"
OUT.mkdir(parents=True, exist_ok=True)
DROP = ("access_token", "file_system_access_token", "client", "raise_on_failure", "show", "track")


def key_of(eid):
    return eid.replace("/", "~").replace("|", "__")


def norm_hist(line):
    d = json.loads(line)
    data = {k: v for k, v in (d.get("data") or {}).items()
            if k not in ("access_token", "file_system_access_token")}
    return [d.get("method"), d.get("url"), data]


def ms(rows):
    return collections.Counter(rows or [])


def cmp_stored(saved, SA, SB, SC, tag):
    """Compare a replayed snapshot with damage_out/snapshots in its stored form."""
    bad = []
    S = {"A": SA, "B": SB, "C": SC}[tag]
    for t, rows in saved[tag].items():
        if ms(S.get(t)) != ms(rows):
            bad.append(t)
    for t, n in saved["static_row_counts"].items():
        if len(S.get(t, [])) != n:
            bad.append(t)
    for t, cnt in saved["row_counts"].items():
        if len(S.get(t, [])) != cnt[tag]:
            bad.append(t)
    pre = {"B": ("A", SA, "AB"), "C": ("B", SB, "BC")}.get(tag)
    if pre:
        for t, dl in saved["big_table_deltas"].items():
            a, b = ms(pre[1].get(t)), ms(S.get(t))
            add, rem = list((b - a).elements()), list((a - b).elements())
            for mine, st in ((add, dl[f"{pre[2]}_added"]), (rem, dl[f"{pre[2]}_removed"])):
                if len(st) < 400:
                    ok = ms(mine) == ms(st)
                else:
                    ok = len(mine) >= 400 and not (ms(st) - ms(mine))
                if not ok:
                    bad.append(t)
    return sorted(set(bad))


def last_exc(o):
    return next((l.strip() for l in reversed((o or "").splitlines())
                 if l.strip().startswith(("Exception", "Error", "{"))), "")[:200]


def capture(ep):
    key = key_of(ep["episode_id"])
    td = (PROJ / ep["path"]).resolve()
    blocks = A.parse_blocks(td / "logs" / "environment_io.md")
    fi = {b["index"]: i for i, b in enumerate(blocks)}[int(ep["block"])]
    apps = D.apps_of(ep["write_confirmed"], [])
    exp = "cfm_" + key[-70:].replace("~", "_")
    res = dict(key=key, episode_id=ep["episode_id"], data_version=ep["data_version"],
               group=ep["group"], n_blocks=len(blocks), fi=fi)
    os.chdir(STAND)
    from appworld import AppWorld
    from appworld.requester import Requester
    calls, phase, inner, world = [], ["prefix", None], None, None
    try:
        world = AppWorld(task_id=ep["task_id"], experiment_name=exp)
        rec = D.Recorder(world, STAND / "work" / "cfm_tmp", apps)
        rec.is_write = A.is_write
        rec.enable()                          # armed stays False: no per-write snapshots
        inner = Requester.request

        def logged(self_r, _app_name, _api_name, *a, **kw):
            err = resp = None
            try:
                resp = inner(self_r, _app_name, _api_name, *a, **kw)
                return resp
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:400]
                raise
            finally:
                calls.append(dict(i=len(calls), phase=phase[0], blk=phase[1],
                                  api=f"{_app_name}.{_api_name}",
                                  args={k: v for k, v in kw.items() if k not in DROP},
                                  ok=err is None, error=err,
                                  http_n=len(getattr(getattr(self_r, "request_tracker", None), "requests", []) or []),
                                  response=(json.dumps(resp, default=str, ensure_ascii=False)[:1500]
                                            if err is None else None)))
        Requester.request = logged
        for i in range(fi):
            phase[1] = blocks[i]["index"]
            world.execute(blocks[i]["code"])
        SA, ea = rec.snapshot("A")
        phase[0], phase[1] = "block", blocks[fi]["index"]
        out0 = world.execute(blocks[fi]["code"])
        SB, eb = rec.snapshot("B")
        n_through_block = len(calls)
        phase[0] = "cont"
        for j in range(fi + 1, len(blocks)):
            phase[1] = blocks[j]["index"]
            world.execute(blocks[j]["code"])
        SC, ec = rec.snapshot("C")
        Requester.request = inner
        rec.disable()
        res["snap_err"] = (ea or eb or ec)[:200]
        orig = blocks[fi].get("output") or ""
        res["block_failed"] = int("Execution failed" in (out0 or ""))
        res["orig_block_failed"] = int("Execution failed" in orig or "Traceback" in orig)
        res["block_exc"], res["orig_exc"] = last_exc(out0), last_exc(orig)
        # [main] legacy logs cut the exception text ("Exception"), so the historical last
        # line must be a prefix of the replayed one (equality when it is complete)
        res["ctl_fail"] = int(res["block_failed"] == res["orig_block_failed"] and
                              (not res["block_failed"] or res["block_exc"].startswith(res["orig_exc"])))
        saved = json.load(open(PROJ / "damage_out" / "snapshots" / f"{key}.json"))
        bB, bC = cmp_stored(saved, SA, SB, SC, "B"), cmp_stored(saved, SA, SB, SC, "C")
        res["ctl_snapB"], res["ctl_snapC"] = int(not bB and not eb), int(not bC and not ec)
        if bB: res["ctl_snapB_tables"] = bB[:10]
        if bC: res["ctl_snapC_tables"] = bC[:10]
        world.close()
        world = None
        mine_p = STAND / "experiments" / "outputs" / exp / "tasks" / ep["task_id"] / "logs" / "api_calls.jsonl"
        mine = [norm_hist(l) for l in open(mine_p) if l.strip()]
        hist = [norm_hist(l) for l in open(td / "logs" / "api_calls.jsonl") if l.strip()]
        res["n_calls"], res["n_through_block"], res["n_http"], res["n_hist"] = \
            len(calls), n_through_block, len(mine), len(hist)

        def first_diff(n):
            a, b = mine[:n], hist[:n]
            f = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), None)
            if f is None and len(a) != len(b):
                f = min(len(a), len(b))
            return f
        # [main] the block boundary is AppWorld's own request counter (http_n), not the
        # number of hook records: calls rejected client-side (NumRequestsLimitError,
        # unexpected parameter) reach the hook but never the HTTP log
        nb = calls[n_through_block - 1]["http_n"] if n_through_block else 0
        res["n_http_through_block"] = nb
        f = first_diff(nb)
        # [main] the boundary itself is checked too: the first call after the block must
        # also agree with history (or both logs end there)
        nxt_ok = (len(hist) == nb) or (len(mine) > nb and mine[nb] == hist[nb])
        res["ctl_hist"] = int(f is None and nxt_ok and (not calls or calls[-1]["http_n"] == len(mine)))
        if f is not None:
            res["ctl_hist_first_diff"] = dict(pos=f, replay=mine[f] if f < len(mine) else None,
                                              hist=hist[f] if f < len(hist) else None)
        g = first_diff(max(len(mine), len(hist)))
        res["ctl_hist_full"] = int(g is None)
        if g is not None:
            res["ctl_hist_full_first_diff"] = g
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"[:300]
        res["trace"] = traceback.format_exc()[-600:]
    finally:
        try:
            from appworld.requester import Requester as R2
            if inner is not None and R2.request is not inner:
                R2.request = inner
        except Exception:
            pass
        try:
            if world is not None:
                world.close()
        except Exception:
            pass
        os.chdir(PROJ)
    for k in ("ctl_snapB", "ctl_hist", "ctl_fail"):
        res.setdefault(k, 0)
    res["replay_mismatch"] = int(not (res["ctl_snapB"] and res["ctl_hist"] and res["ctl_fail"]))
    with open(OUT / f"{key}.jsonl", "w") as f:
        for c in calls:
            f.write(json.dumps(c, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return res


if __name__ == "__main__":
    r = capture(json.loads(sys.argv[1]))
    print("RESULT " + json.dumps(r, ensure_ascii=False, default=str))
