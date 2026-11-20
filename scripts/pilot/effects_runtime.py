#!/usr/bin/env python3
"""The `effects.call(operation_id, api, arguments)` interface, injected into the agent's
namespace as a preamble block.

Contract (fixed before the pilot):
  new id                                  -> execute
  completed id, same api and arguments    -> return the stored result, do not call
  completed id, different api or arguments-> operation_conflict, do not execute
  reliable failure with no effect         -> a corrected attempt under the same id is allowed
  unknown outcome                         -> unresolved, never repeated automatically
Success is decided by the API contract: a call that returns is a success; an exception
carrying an HTTP 4xx is a reliable failure with no effect; anything else is unknown.
Access tokens are excluded from comparison and from messages. Reads are not cached and
never go through this interface. No argument-similarity matching is used.
"""

PREAMBLE = '''
import json as _json

class _Effects:
    """mode: "observe" (journal only) or "enforce" (contract applied)."""

    def __init__(self, mode):
        self.mode = mode
        self.log = []
        self.state = {}          # operation_id -> record

    @staticmethod
    def _clean(args):
        return {k: v for k, v in (args or {}).items()
                if k not in ("access_token", "password", "file_system_access_token")}

    @staticmethod
    def _resolve(api):
        app, _, name = api.partition(".")
        return getattr(getattr(apis, app), name)

    @staticmethod
    def _classify(exc):
        t = str(exc)
        if "Response status code is 4" in t:
            return "failed_no_effect"
        return "unknown"

    def call(self, operation_id, api, arguments=None):
        arguments = dict(arguments or {})
        clean = self._clean(arguments)
        prev = self.state.get(operation_id)
        entry = dict(op=operation_id, api=api, args=clean, decision="", status="",
                     bypass=False)
        if prev is not None and prev["status"] == "completed" and self.mode == "enforce":
            if prev["api"] == api and prev["args"] == clean:
                entry.update(decision="returned_stored", status="completed")
                self.log.append(entry)
                return prev["result"]
            entry.update(decision="operation_conflict", status="blocked")
            self.log.append(entry)
            raise RuntimeError(
                "operation_conflict: operation %r already executed as %s with different "
                "arguments; a new action requires a new operation_id"
                % (operation_id, prev["api"]))
        if prev is not None and prev["status"] == "unknown" and self.mode == "enforce":
            entry.update(decision="unresolved", status="unresolved")
            self.log.append(entry)
            raise RuntimeError(
                "unresolved: outcome of operation %r unknown, automatic repeat "
                "forbidden" % (operation_id,))
        try:
            res = self._resolve(api)(**arguments)
        except Exception as exc:
            st = self._classify(exc)
            entry.update(decision="executed", status=st)
            self.log.append(entry)
            self.state[operation_id] = dict(api=api, args=clean, status=st, result=None)
            raise
        entry.update(decision="executed", status="completed")
        self.log.append(entry)
        self.state[operation_id] = dict(api=api, args=clean, status="completed",
                                        result=res)
        return res

    def dump(self):
        return _json.dumps(self.log, default=str)


effects = _Effects(%MODE%)
'''


def preamble(mode):
    assert mode in ("observe", "enforce")
    return PREAMBLE.replace("%MODE%", repr(mode))


HIDE_FRAMES = ("_Effects.call", "self._resolve(api)(**arguments)", "effects_runtime")


def clean_traceback(text):
    """Hide the wrapper's own frames by a rule fixed in advance: any traceback line
    naming _Effects.call or the resolve line is dropped, together with its source line."""
    out, skip = [], False
    for line in (text or "").splitlines():
        if any(h in line for h in HIDE_FRAMES):
            skip = True
            continue
        if skip and line.startswith("    "):
            skip = False
            continue
        skip = False
        out.append(line)
    return "\n".join(out)
