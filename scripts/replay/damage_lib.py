#!/usr/bin/env python3
"""Shared replay + snapshot machinery for the damage estimate.

Runs under either stand: appworld 0.1.0 (data 0.1.0, cwd=replay_root) or
appworld 0.2.0.dev0 (data 0.2.0, cwd=stand020). The only stand-specific thing is the
working directory, which the caller sets.

Snapshot: FULL row contents of every non-FTS table of the target apps, with no row-count
cap. `cart_entries` presence is asserted for amazon tasks as an instrument check.
"""
import builtins, collections, json, os, pathlib, shutil, sqlite3, sys, time

PROJ = pathlib.Path(__file__).resolve().parent
VOL_FIELDS = ("created_at", "updated_at")


class BudgetExceeded(Exception):
    pass


def now():
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)


def _save_full(world, out_dir, app_names):
    # the module moved between 0.1.0 and 0.2.0.dev0
    try:
        from appworld.apps.lib.apis.local_remote import save_local_dbs
    except ModuleNotFoundError:
        from appworld.apps.api_lib import save_local_dbs
    save_local_dbs(from_db_home_path=world.models_to_db_home_path,
                   to_db_home_path=str(out_dir), format="full",
                   app_names=list(app_names), delete_if_exists=True,
                   skip_mandatory_apps=True, save_model_hashes=False, vaccum=False)


class Recorder:
    """Intercepts Requester.request; snapshots full table state on demand."""

    def __init__(self, world, work_dir, apps):
        self.world = world
        self.dir = pathlib.Path(work_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.apps = sorted(apps)
        self.calls = []          # every request, in order
        self.write_diffs = []    # diffs around writes while `armed`
        self.armed = False
        self.is_write = None     # injected by the caller
        self._dn = open(os.devnull, "w")
        self.snap_bytes = 0
        self.snap_seconds = 0.0
        # CHAINING: the DB can only change through Requester.request, so between two
        # consecutive intercepted writes nothing moves. The "after" snapshot of write k
        # is therefore the "before" snapshot of write k+1: one snapshot per write
        # instead of two. `prev_state` holds it; it is seeded with snapshot B.
        self.prev_state = None
        self.n_snapshots = 0
        # CAP, fixed before results were seen: an episode may not spend more than
        # MAX_WRITES intercepted writes or MAX_SECONDS of wall clock. One legacy episode
        # ran 31 min at 5.4 GB RSS. A capped episode is kept in the denominator as
        # undecidable, never dropped.
        self.max_writes = int(os.environ.get("MAX_WRITES", "400"))
        self.max_seconds = float(os.environ.get("MAX_SECONDS", "300"))
        # hard per-episode wall clock. One legacy episode replays a single block with
        # 1378 API calls (the original agent itself timed out on it) and ran 30+ min.
        # Declared before results were read and applied to both groups alike; an
        # episode that trips it is NOT dropped, it is recorded as not reproduced and
        # stays in the denominator as undecidable.
        self.episode_max = float(os.environ.get("EPISODE_MAX", "420"))
        self.t_start = now()
        self.capped = ""
        self.budget_blown = False

    def snapshot(self, tag):
        d = self.dir / f"snap_{tag}"
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
        guard = getattr(self.world, "safety_guard", None)
        was_on = getattr(builtins.open, "__name__", "") == "read_only_open"
        so, se = sys.stdout, sys.stderr
        t0 = now()
        out, err = {}, ""
        try:
            sys.stdout = sys.stderr = self._dn
            if guard is not None:
                guard.disable()
            _save_full(self.world, d, self.apps)
            for f in sorted(d.glob("*.db")):
                self.snap_bytes += f.stat().st_size
                con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
                con.row_factory = sqlite3.Row
                try:
                    tabs = [t[0] for t in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                    for t in tabs:
                        if t.startswith("sqlite_") or "_fts" in t:
                            continue
                        try:
                            rows = con.execute(f"SELECT * FROM '{t}'").fetchall()
                        except Exception:
                            continue
                        out[f"{f.stem}.{t}"] = [
                            json.dumps({k: r[k] for k in r.keys()},
                                       default=str, sort_keys=True) for r in rows]
                finally:
                    con.close()
        except Exception as e:
            import traceback
            err = traceback.format_exc()[-300:]
        finally:
            try:
                if guard is not None and was_on:
                    guard.enable()
            except Exception:
                pass
            sys.stdout, sys.stderr = so, se
            shutil.rmtree(d, ignore_errors=True)
        self.snap_seconds += now() - t0
        self.n_snapshots += 1
        return out, err

    def enable(self):
        from appworld.requester import Requester
        self._orig = Requester.request
        rec = self

        def patched(self_r, _app_name, _api_name, client=None, raise_on_failure=None,
                    show=False, track=True, **data):
            key = f"{_app_name}.{_api_name}"
            if now() - rec.t_start > rec.episode_max:
                rec.budget_blown = True      # recorded, never raised: raising into the
                                             # agent's own try/except can turn a bounded
                                             # retry loop into an unbounded one
            watch = rec.armed and rec.is_write is not None and rec.is_write(_app_name, _api_name)
            if watch and not rec.capped:
                if len(rec.write_diffs) >= rec.max_writes:
                    rec.capped = f"limit {rec.max_writes} write-calls"
                elif now() - rec.t_start > rec.max_seconds:
                    rec.capped = f"limit {rec.max_seconds:.0f} s"
            if rec.capped:
                watch = False
            before = rec.prev_state if watch else None
            if watch and before is None:
                before = rec.snapshot("w_before")[0]
            err = res = None
            try:
                res = rec._orig(self_r, _app_name, _api_name, client=client,
                                raise_on_failure=raise_on_failure, show=show,
                                track=track, **data)
                return res
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:300]
                raise
            finally:
                rec.calls.append(dict(api=key, phase="armed" if rec.armed else "pre",
                                      error=err))
                if watch:
                    after = rec.snapshot("w_after")[0]
                    rec.prev_state = after
                    rec.write_diffs.append(dict(
                        api=key, error=err,
                        args={k: ("<token>" if isinstance(v, str) and len(v) > 60 else v)
                              for k, v in data.items()},
                        response=(json.dumps(res, default=str)[:300]
                                  if res is not None else None),
                        delta=row_delta(before, after)))
        Requester.request = patched

    def disable(self):
        from appworld.requester import Requester
        Requester.request = self._orig


def row_delta(before, after):
    """Rows added and removed per table, in full."""
    out = {}
    for tab in set(list(before or {}) + list(after or {})):
        b = collections.Counter((before or {}).get(tab, []))
        a = collections.Counter((after or {}).get(tab, []))
        add = list((a - b).elements())
        rem = list((b - a).elements())
        if add or rem:
            out[tab] = dict(added=[x[:600] for x in add[:12]],
                            removed=[x[:600] for x in rem[:12]],
                            n_added=len(add), n_removed=len(rem))
    return out


def apps_of(write_confirmed, task_apps):
    """Target apps: those of the confirmed writes, plus amazon-side dependencies."""
    apps = set()
    for w in (write_confirmed or "").split(";"):
        w = w.split("@")[0].strip()
        if "." in w:
            apps.add(w.split(".")[0])
    return sorted(apps or set(task_apps))
