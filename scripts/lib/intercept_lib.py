#!/usr/bin/env python3
"""A1: intercept the target repeated call at the API boundary during NORMAL execution
of the recovery block, and capture the stdout AppWorld discards.

Both hooks are non-invasive:
  * appworld.environment.capture_output is wrapped so the captured stdout of a failing
    block can be read after execute() returns (the environment itself drops it).
  * appworld.requester.Requester.request is wrapped: it is the single boundary through
    which every apis.<app>.<api>(...) call passes, and it returns the response dict.
"""
import json, os, shutil, sys, tempfile, pathlib, collections, contextlib

MAX_STR = 300


def _safe(v, depth=0):
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v if len(v) <= MAX_STR else v[:MAX_STR] + f"...<{len(v)}>"
    if depth >= 2:
        return f"<{type(v).__name__}>"
    if isinstance(v, dict):
        return {str(k): _safe(x, depth + 1) for k, x in list(v.items())[:25]}
    if isinstance(v, (list, tuple)):
        return [_safe(x, depth + 1) for x in list(v)[:25]]
    return f"<{type(v).__name__}>"


def patch_capture():
    """-> a dict whose 'last' key holds the most recent capture object."""
    import appworld.environment as E
    holder = {"last": None}
    orig = E.capture_output

    class Wrapper:
        def __init__(self, *a, **kw):
            self._c = orig(*a, **kw)

        def __enter__(self):
            cap = self._c.__enter__()
            holder["last"] = cap
            return cap

        def __exit__(self, *a):
            return self._c.__exit__(*a)

    E.capture_output = Wrapper
    return holder


def block_frame_info():
    """Line number and a digest of the locals in the frame that runs the agent's block."""
    f = sys._getframe()
    while f is not None:
        name = f.f_code.co_filename
        if "ipython-input" in name or "python-input" in name or name.startswith("<"):
            if f.f_code.co_name == "<module>":
                return f.f_lineno, {k: _safe(v) for k, v in list(f.f_locals.items())[:60]
                                    if not k.startswith("_")}
        f = f.f_back
    return None, {}


class Interceptor:
    def __init__(self, world, target_api, snap_root, snapshot_writes=False,
                 is_write=None):
        self.world = world
        self.target = target_api
        self.snap_root = pathlib.Path(snap_root)
        self.snap_root.mkdir(parents=True, exist_ok=True)
        self.block = None                 # set by the driver before each execute()
        self.snapshot_writes = snapshot_writes   # B3: snapshot around EVERY write call
        self.is_write = is_write or (lambda app, api: False)
        self.write_events = []
        self.records = []                 # every API call, per block
        self.target_hits = []             # detailed records for the target call
        self._line_hits = collections.Counter()
        self._orig = None

    # ---- DB snapshot at an arbitrary moment ----
    def _prepare(self):
        """Pre-open real streams and the snapshot directories BEFORE the safety guard
        is active: inside a block `open()` is patched read-only and faulthandler needs
        a real fd, so neither can be obtained on demand."""
        self._dn_out = open(os.devnull, "w")
        self._dn_err = open(os.devnull, "w")
        for tag in ("before", "after"):
            (self.snap_root / tag).mkdir(parents=True, exist_ok=True)

    def snapshot(self, tag):
        import builtins
        d = self.snap_root / tag
        guard = getattr(self.world, "safety_guard", None)
        # the guard is only active WHILE a block executes; snapshots taken outside a
        # block must not switch it on afterwards
        guard_was_on = getattr(builtins.open, "__name__", "") == "read_only_open"
        so, se = sys.stdout, sys.stderr
        out = {}
        try:
            sys.stdout, sys.stderr = self._dn_out, self._dn_err
            if guard is not None:
                guard.disable()
            for f in list(d.glob("*.jsonl")):
                f.unlink()
            self.world._save_state(str(d))
            for f in sorted(d.glob("*.jsonl")):
                rows = [l.strip() for l in open(f) if l.strip()]
                if rows:
                    out[f.stem] = rows
        except Exception:
            import traceback as _tb
            out = {"__error__": _tb.format_exc()[-1200:]}
        finally:
            try:
                if guard is not None and guard_was_on:
                    guard.enable()
            except Exception:
                pass
            sys.stdout, sys.stderr = so, se
        return out

    def enable(self):
        self._prepare()
        from appworld.requester import Requester
        self._orig = Requester.request
        itc = self

        def patched(self_r, _app_name, _api_name, client=None, raise_on_failure=None,
                    show=False, track=True, **data):
            key = f"{_app_name}.{_api_name}"
            is_target = (itc.target and key == itc.target and itc.block == "repeat")
            want_write_snap = (itc.snapshot_writes and itc.is_write(_app_name, _api_name)
                               and str(itc.block).startswith("cont"))
            line, locs = block_frame_info()
            itc._line_hits[(itc.block, key, line)] += 1
            iteration = itc._line_hits[(itc.block, key, line)]
            before = itc.snapshot("before") if (is_target or want_write_snap) else None
            err = None
            try:
                resp = itc._orig(self_r, _app_name, _api_name, client=client,
                                 raise_on_failure=raise_on_failure, show=show,
                                 track=track, **data)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"[:400]
                if want_write_snap:
                    itc.write_events.append(dict(block=itc.block, api=key, args=_safe(data),
                                                 response=None, error=err, line=line,
                                                 iteration=iteration,
                                                 before=before, after=itc.snapshot("after")))
                if is_target:
                    after = itc.snapshot("after")
                    itc.target_hits.append(dict(api=key, args=_safe(data), response=None,
                                                error=err, line=line, iteration=iteration,
                                                locals=locs, before=before, after=after))
                itc.records.append(dict(block=itc.block, api=key, args=_safe(data),
                                        response=None, error=err, line=line,
                                        iteration=iteration))
                raise
            if want_write_snap:
                itc.write_events.append(dict(block=itc.block, api=key, args=_safe(data),
                                             response=_safe(resp), error=None, line=line,
                                             iteration=iteration,
                                             before=before, after=itc.snapshot("after")))
            if is_target:
                after = itc.snapshot("after")
                itc.target_hits.append(dict(api=key, args=_safe(data), response=_safe(resp),
                                            error=None, line=line, iteration=iteration,
                                            locals=locs, before=before, after=after))
            itc.records.append(dict(block=itc.block, api=key, args=_safe(data),
                                    response=_safe(resp), error=None, line=line,
                                    iteration=iteration))
            return resp

        Requester.request = patched

    def disable(self):
        if self._orig is not None:
            from appworld.requester import Requester
            Requester.request = self._orig
            self._orig = None
