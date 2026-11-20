#!/usr/bin/env python3
"""FROZEN MEASUREMENT PATH: snapshot, diff, identity, flags.

Everything that turns a replay into a measurement lives here, so it can be hashed.

What changed relative to the ad-hoc code this replaces, and why:
  * every snapshot now returns a MANIFEST (expected / read / failed tables). An
    unreadable table is `unknown`, never "all rows removed". The previous code caught
    the exception and returned {}, which was indistinguishable from an empty database
    and produced phantom whole-table deletions.
  * the phantom filter based on row counts is GONE. A genuine clear_cart over 50 items
    is a real event; only a read failure makes a change unknown.
  * entity identifiers are read from the URL path as well as the body, because AppWorld
    puts ids in the path (/amazon/cart/<product_id>).
  * no table is skipped for size; large tables are kept whole in memory and, when
    persisted, as base + delta with the manifest recording that.
"""
import builtins, collections, json, os, pathlib, shutil, sqlite3, sys, time

VOLATILE = ("id", "record_hash", "created_at", "updated_at")
# Golden-test hook: table names listed here raise on read, so the `failed` bookkeeping
# can be exercised deterministically. Empty in production; its emptiness is part of the
# freeze hash.
FAIL_TABLES = set()
CART_TABLES = ("cart_entries",)
PATH_TABLES = ("files", "directories")


def now():
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)


def _save_full(world, out_dir, app_names):
    try:
        from appworld.apps.lib.apis.local_remote import save_local_dbs
    except ModuleNotFoundError:
        from appworld.apps.api_lib import save_local_dbs
    save_local_dbs(from_db_home_path=world.models_to_db_home_path,
                   to_db_home_path=str(out_dir), format="full",
                   app_names=list(app_names), delete_if_exists=True,
                   skip_mandatory_apps=True, save_model_hashes=False, vaccum=False)


_DEVNULL = None


def prepare(work_dir, tags=("before", "after", "A", "B", "C", "mid", "s")):
    """Open the /dev/null handles and create the snapshot directories BEFORE any block
    runs. AppWorld's safety guard replaces builtins.open with a read-only version while
    a block executes, so doing either lazily makes the first in-block snapshot fail.
    Found by golden case 8, which reported dump_ok=False instead of a silent empty diff.
    """
    global _DEVNULL
    if _DEVNULL is None:
        _DEVNULL = open(os.devnull, "w")
    root = pathlib.Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    for t in tags:
        (root / f"snap_{t}").mkdir(parents=True, exist_ok=True)
    return _DEVNULL


def snapshot(world, apps, work_dir, tag="s"):
    """-> (state, manifest). state[table] = list of row-JSON strings."""
    d = pathlib.Path(work_dir) / f"snap_{tag}"
    dn = prepare(work_dir) if _DEVNULL is None else _DEVNULL
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    guard = getattr(world, "safety_guard", None)
    was_on = getattr(builtins.open, "__name__", "") == "read_only_open"
    so, se = sys.stdout, sys.stderr
    state = {}
    man = dict(apps=sorted(apps), expected=[], read=[], failed=[], dump_ok=True, error="")
    try:
        sys.stdout = sys.stderr = dn
        if guard is not None:
            guard.disable()
        _save_full(world, d, apps)
        for f in sorted(d.glob("*.db")):
            con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            try:
                tabs = [t[0] for t in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                for t in tabs:
                    if t.startswith("sqlite_") or "_fts" in t:
                        continue
                    name = f"{f.stem}.{t}"
                    man["expected"].append(name)
                    try:
                        if t in FAIL_TABLES or name in FAIL_TABLES:
                            raise sqlite3.DatabaseError("table marked as unreadable")
                        rows = con.execute(f"SELECT * FROM '{t}'").fetchall()
                    except Exception:
                        man["failed"].append(name)
                        continue
                    state[name] = [json.dumps({k: r[k] for k in r.keys()},
                                              default=str, sort_keys=True) for r in rows]
                    man["read"].append(name)
            finally:
                con.close()
    except Exception as e:
        import traceback
        man["dump_ok"] = False
        man["error"] = traceback.format_exc()[-300:]
    finally:
        try:
            if guard is not None and was_on:
                guard.enable()
        except Exception:
            pass
        sys.stdout, sys.stderr = so, se
        shutil.rmtree(d, ignore_errors=True)
    return state, man


def diff(before, after, man_before=None, man_after=None):
    """-> {table: {added, removed, n_added, n_removed, status}}.

    status is `ok` when the table was read in both snapshots, `unknown` otherwise; an
    unknown table never contributes added/removed rows.
    """
    rb = set((man_before or {}).get("read", before.keys()))
    ra = set((man_after or {}).get("read", after.keys()))
    # expected covers tables that exist but could not be read; they must surface as
    # `unknown` rather than silently vanish from the diff
    exp = set((man_before or {}).get("expected", [])) | set((man_after or {}).get("expected", []))
    out = {}
    for t in sorted(set(list(before) + list(after)) | rb | ra | exp):
        if (man_before and t not in rb) or (man_after and t not in ra):
            out[t] = dict(added=[], removed=[], n_added=0, n_removed=0, status="unknown")
            continue
        cb = collections.Counter(before.get(t, []))
        ca = collections.Counter(after.get(t, []))
        add, rem = list((ca - cb).elements()), list((cb - ca).elements())
        if add or rem:
            out[t] = dict(added=add, removed=rem, n_added=len(add), n_removed=len(rem),
                          status="ok")
    return out


def substance(row):
    try:
        d = json.loads(row)
    except Exception:
        return "TRUNC:" + row[:200]
    return json.dumps({k: v for k, v in d.items() if k not in VOLATILE}, sort_keys=True)


def row_id(row):
    try:
        return json.loads(row).get("id")
    except Exception:
        return None


def cart_map(rows):
    """(user_id, product_id) -> (quantity, gift_wrap_quantity)."""
    m = {}
    for r in rows:
        try:
            d = json.loads(r)
        except Exception:
            continue
        m[(d.get("user_id"), d.get("product_id"))] = (d.get("quantity"),
                                                      d.get("gift_wrap_quantity"))
    return m


def entity_ids(url, data):
    """Identifiers of a request: numeric path segments plus scalar body fields."""
    out = []
    for seg in (url or "").split("?")[0].split("/"):
        if seg.isdigit():
            out.append(int(seg))
    for k, v in (data or {}).items():
        if k in ("access_token", "password", "page_index", "page_limit"):
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(v)
        elif isinstance(v, str) and 3 <= len(v) <= 60 and not v.startswith("ey"):
            out.append(v)
    return out


def episode_flags(A, B, C, man=None):
    """duplicated / accumulated / gone / other_change / unchanged, plus `unknown`
    when any table involved could not be read."""
    flags = collections.Counter()
    unknown = False
    for t in sorted(set(list(B) + list(C))):
        if man and t in set(man.get("failed", [])):
            unknown = True
            continue
        short = t.split(".")[-1]
        if short in CART_TABLES:
            ma, mb, mc = cart_map(A.get(t, [])), cart_map(B.get(t, [])), cart_map(C.get(t, []))
            for k, v in mb.items():
                qc = mc.get(k)
                if qc is None:
                    if k in ma:
                        flags["gone"] += 1
                elif qc != v:
                    flags["accumulated" if (qc[0] or 0) > (v[0] or 0) else "other_change"] += 1
            for k in set(mc) - set(mb):
                flags["other_change"] += 1
            continue
        keep_name = short in PATH_TABLES
        def key(r):
            return r if keep_name else substance(r)
        cb = collections.Counter(key(x) for x in B.get(t, []))
        cc = collections.Counter(key(x) for x in C.get(t, []))
        ca = collections.Counter(key(x) for x in A.get(t, []))
        for k, n in cb.items():
            if cc.get(k, 0) > n:
                flags["duplicated"] += 1
            elif cc.get(k, 0) == 0 and ca.get(k, 0):
                flags["gone"] += 1
        for k, n in cc.items():
            if cb.get(k, 0) == 0 and ca.get(k, 0) == 0:
                flags["other_change"] += 1
    verdict = ("unknown" if unknown and not flags else
               "duplicated" if flags["duplicated"] else
               "accumulated" if flags["accumulated"] else
               "gone" if flags["gone"] and not flags["other_change"] else
               "other_change" if flags["other_change"] else "unchanged")
    return verdict, dict(flags)


def verify_freeze(path="instrument_freeze.json"):
    """Any comparison run must call this first. It refuses to proceed when the frozen
    measurement path has changed; a change means a new golden run and a new freeze."""
    import hashlib
    p = pathlib.Path(path)
    if not p.exists():
        raise RuntimeError("freeze not found: measurement forbidden")
    blob = json.loads(p.read_text())
    bad = []
    for f, h in blob["files"].items():
        q = pathlib.Path(f)
        if not q.exists():
            bad.append(f"{f}: file missing")
        elif hashlib.sha256(q.read_bytes()).hexdigest() != h:
            bad.append(f"{f}: hash did not match")
    if FAIL_TABLES:
        bad.append("FAIL_TABLES is not empty: test hook active")
    if bad:
        raise RuntimeError("freeze violated -> a new golden run is needed: "
                           + "; ".join(bad))
    return blob["freeze_sha"]


class Recorder:
    """Intercepts Requester.request; snapshots around every watched call."""

    def __init__(self, world, apps, work_dir, watch=None):
        self.world, self.apps = world, sorted(apps)
        self.dir = pathlib.Path(work_dir)
        prepare(self.dir)
        self.watch = watch            # callable(app, api) -> bool; None = all writes
        self.events, self.manifests = [], []
        self.armed = False
        self.prev = None              # chained: after(k) == before(k+1)

    def snap(self, tag="s"):
        st, man = snapshot(self.world, self.apps, self.dir, tag)
        self.manifests.append(dict(tag=tag, **{k: man[k] for k in
                                               ("dump_ok", "error", "apps")},
                                   n_expected=len(man["expected"]),
                                   n_read=len(man["read"]),
                                   failed=man["failed"]))
        return st, man

    def enable(self):
        from appworld.requester import Requester
        self._orig = Requester.request
        rec = self

        def patched(self_r, _app_name, _api_name, client=None, raise_on_failure=None,
                    show=False, track=True, **data):
            key = f"{_app_name}.{_api_name}"
            watch = rec.armed and (rec.watch is None or rec.watch(_app_name, _api_name))
            before = bman = None
            if watch:
                if rec.prev is None:
                    before, bman = rec.snap("before")
                else:
                    before, bman = rec.prev
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
                if watch:
                    after, aman = rec.snap("after")
                    rec.prev = (after, aman)
                    rec.events.append(dict(
                        api=key, error=err, args={k: v for k, v in data.items()
                                                  if k != "access_token"},
                        delta=diff(before, after, bman, aman),
                        manifest_ok=bool(bman["dump_ok"] and aman["dump_ok"]
                                         and not bman["failed"] and not aman["failed"])))
        Requester.request = patched

    def disable(self):
        from appworld.requester import Requester
        Requester.request = self._orig
