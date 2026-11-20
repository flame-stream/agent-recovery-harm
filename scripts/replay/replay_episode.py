#!/usr/bin/env python3
"""Replay one episode to the fixed recovery boundary and dump snapshots + call diffs.

Boundary C, fixed for every episode: the END of the available trajectory (the last
recorded block of the run). A = before the failed block, B = right after it.
Writes <out>/<episode>.json ; snapshots A/B/C go to snapshots/, diffs to call_diffs/.
"""
import collections, json, os, pathlib, sys, traceback

PROJ = pathlib.Path(os.environ["PROJ"]).resolve()
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)                       # appworld_audit reads write_apis.txt from cwd
import appworld_audit as A
import damage_lib as D
STAND = pathlib.Path(os.environ["STAND"]).resolve()


def replay(ep, out_root):
    out_root = pathlib.Path(out_root).resolve()
    td = pathlib.Path(ep["path"])
    blocks = A.parse_blocks(td / "logs" / "environment_io.md")
    pos = {b["index"]: i for i, b in enumerate(blocks)}
    fi = pos.get(int(ep["block"]))
    if fi is None:
        return dict(episode_id=ep["episode_id"], ok=0, reason="block not found in the trace")
    apps = D.apps_of(ep["write_confirmed"], [])
    os.chdir(STAND)                  # AppWorld resolves ./data relative to cwd
    from appworld import AppWorld
    t0 = D.now()
    world = None
    try:
        world = AppWorld(task_id=ep["task_id"],
                         experiment_name="dmg_" + ep["episode_id"].replace("/", "_")[-60:])
        rec = D.Recorder(world, STAND / "work" / "tmp", apps)
        rec.is_write = A.is_write
        rec.enable()
        for i in range(0, fi):
            world.execute(blocks[i]["code"])
        SA, ea = rec.snapshot("A")
        world.execute(blocks[fi]["code"])
        SB, eb = rec.snapshot("B")
        rec.prev_state = SB      # seed the chain
        rec.armed = True
        for j in range(fi + 1, len(blocks)):
            world.execute(blocks[j]["code"])
        rec.armed = False
        if rec.budget_blown:
            raise D.BudgetExceeded("episode exceeded the time limit")
        SC, ec = rec.snapshot("C")
        rec.disable()
        cart_ok = (not any(a == "amazon" for a in apps)) or \
                  any("cart_entries" in t for t in SB)
        # persist only the tables whose contents move somewhere in A->B->C; the static
        # catalogue (products, sellers, ...) is identical in all three and would be 95%
        # of the bytes. Unchanged tables are kept as row counts, so nothing is silently
        # lost from the record.
        moving = {t for t in set(list(SA) + list(SB) + list(SC))
                  if not (SA.get(t) == SB.get(t) == SC.get(t))}
        static = {t: len(SB.get(t, [])) for t in set(list(SA) + list(SB) + list(SC))
                  if t not in moving}
        # Large moving tables (gmail.user_email_threads has ~48k rows) are stored as
        # base + deltas instead of three full copies: what changed is preserved exactly,
        # only the listing of untouched rows in such tables is dropped.
        BIG = 2000
        keep = {"A": {}, "B": {}, "C": {}}
        deltas, counts = {}, {}
        for t in moving:
            a, b, c = SA.get(t, []), SB.get(t, []), SC.get(t, [])
            counts[t] = dict(A=len(a), B=len(b), C=len(c))
            if max(len(a), len(b), len(c)) <= BIG:
                keep["A"][t], keep["B"][t], keep["C"][t] = a, b, c
            else:
                sa, sb, sc = collections.Counter(a), collections.Counter(b), collections.Counter(c)
                deltas[t] = dict(
                    AB_added=list((sb - sa).elements())[:400],
                    AB_removed=list((sa - sb).elements())[:400],
                    BC_added=list((sc - sb).elements())[:400],
                    BC_removed=list((sb - sc).elements())[:400])
        base = out_root / "snapshots"
        base.mkdir(parents=True, exist_ok=True)
        key = ep["episode_id"].replace("/", "~").replace("|", "__")
        json.dump(dict(moving=sorted(moving), static_row_counts=static,
                       row_counts=counts, big_table_deltas=deltas, **keep),
                  open(base / f"{key}.json", "w"))
        dd = out_root / "call_diffs"
        dd.mkdir(parents=True, exist_ok=True)
        json.dump(rec.write_diffs, open(dd / f"{key}.json", "w"), ensure_ascii=False)
        return dict(episode_id=ep["episode_id"], ok=1, reason="",
                    seconds=round(D.now() - t0, 1),
                    snap_mb=round(rec.snap_bytes / 1e6, 1),
                    snap_seconds=round(rec.snap_seconds, 1),
                    n_blocks=len(blocks), tail=len(blocks) - fi - 1,
                    n_write_diffs=len(rec.write_diffs),
                    n_moving_tables=len(moving),
                    n_snapshots=rec.n_snapshots, capped=rec.capped,
                    n_calls=len(rec.calls), cart_present=int(cart_ok),
                    snap_err=(ea or eb or ec)[:120])
    except D.BudgetExceeded as e:
        return dict(episode_id=ep["episode_id"], ok=0,
                    reason=f"time limit exceeded: {e}"[:160],
                    undecidable="budget", seconds=round(D.now() - t0, 1))
    except Exception as e:
        if "BudgetExceeded" in type(e).__name__ or "exceeded" in str(e):
            return dict(episode_id=ep["episode_id"], ok=0,
                        reason="time limit exceeded", undecidable="budget",
                        seconds=round(D.now() - t0, 1))
        return dict(episode_id=ep["episode_id"], ok=0,
                    reason=f"{type(e).__name__}: {e}"[:160],
                    seconds=round(D.now() - t0, 1))
    finally:
        try:
            if world is not None:
                world.close()
        except Exception:
            pass
        os.chdir(PROJ)
