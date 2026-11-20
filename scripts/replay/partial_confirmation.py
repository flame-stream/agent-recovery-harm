#!/usr/bin/env python3
"""Step 2: did the failed block really write something?

For every episode: the full A->B diff must contain a change matching the write the
detector confirmed before the failing line — same app, and, when the request carries
entity identifiers, a changed row containing them.

RULES FIXED BEFORE RUNNING
  confirmed              — such a change exists.
  not_confirmed          — no change in the app of the confirmed write. Reason:
                           `rejected` if that request errored in the historical log,
                           `idempotent` if it succeeded but moved nothing,
                           `detector_error` if the API is not actually a write.
  undeterminable_partial — the snapshot of A or B failed, so the diff is not evidence.
Entity matching uses the request as recorded in api_calls.jsonl (path ids included),
because agents pass arguments through variables.
"""
import collections, csv, json, pathlib, re, sys
sys.path.insert(0, ".")
import appworld_audit as A
from fresh_detect2 import route_of
csv.field_size_limit(10**9)
TOKEN = re.compile(r"^ey[A-Za-z0-9_\-]{10,}")
SKIP = {"access_token", "password", "page_index", "page_limit", "username"}
VOL = ("id", "record_hash", "created_at", "updated_at")


def ids_of(data, url):
    out = []
    for k, v in (data or {}).items():
        if k in SKIP or isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(str(v))
        elif isinstance(v, str) and 3 <= len(v) <= 60 and not TOKEN.match(v):
            out.append(v)
    for seg in (url or "").split("?")[0].split("/"):
        if seg.isdigit():
            out.append(seg)
    return out


def stream(td):
    out = []
    f = td / "logs" / "api_calls.jsonl"
    if not f.exists():
        return out
    for line in f.open():
        try:
            d = json.loads(line)
        except Exception:
            continue
        out.append((route_of(d.get("url"), d.get("method")), d.get("data") or {},
                    d.get("url") or ""))
    return out


def find_request(blocks, i, api, st):
    """The api_calls entry belonging to this block's confirmed write."""
    cur, picked = 0, None
    for k in range(0, i + 1):
        fl = A.block_outcome(blocks[k]["output"])["fail_line"]
        conf, _ = A.executed_calls(blocks[k]["code"], fl)
        for app, name, _l in conf:
            nm = f"{app}.{name}"
            j = next((x for x in range(cur, min(cur + 500, len(st))) if st[x][0] == nm), None)
            if j is None:
                continue
            cur = j + 1
            if k == i and nm == api:
                picked = st[j]
    return picked


def diff_rows(A_, B_, app):
    rows = []
    for t in set(list(A_) + list(B_)):
        if not t.startswith(app + "."):
            continue
        ca = collections.Counter(A_.get(t, []))
        cb = collections.Counter(B_.get(t, []))
        rows += list((cb - ca).elements()) + list((ca - cb).elements())
    return rows


def main():
    reg = {r["episode_id"]: r for r in csv.DictReader(open("episode_registry.csv"))}
    mp = list(csv.DictReader(open("blind_labels_random_map.csv")))
    bad = set(json.load(open("instrument_undecidable.json")))
    out = []
    cache = {}
    for m in mp:
        eid = m["episode_id"]
        ep = reg[eid]
        p = pathlib.Path("damage_out/snapshots") / (eid.replace("/", "~").replace("|", "__") + ".json")
        apis = [w.split("@")[0] for w in (ep["write_confirmed"] or "").split(";") if w]
        base = dict(slot=m["slot"], episode_id=eid, group=m["group"],
                    experiment=m["experiment"], task_id=ep["task_id"], block=ep["block"],
                    source_run=ep["source_run"], confirmed_apis=";".join(apis))
        if eid in bad or not p.exists():
            out.append(dict(base, status="undeterminable_partial",
                            reason="failed snapshot A/B", matched_api="", n_diff_rows=0))
            continue
        s = json.load(open(p))
        td = pathlib.Path(ep["path"])
        if td not in cache:
            cache[td] = (A.parse_blocks(td / "logs" / "environment_io.md"), stream(td))
        blocks, st = cache[td]
        pos = {b["index"]: k for k, b in enumerate(blocks)}
        i = pos.get(int(ep["block"]))
        status = reason = matched = ""
        ndiff = 0
        for api in apis:
            app = api.split(".")[0]
            rows = diff_rows(s["A"], s["B"], app)
            ndiff = max(ndiff, len(rows))
            if not rows:
                continue
            req = find_request(blocks, i, api, st) if i is not None else None
            ids = ids_of(req[1], req[2]) if req else []
            if not ids or any(all(v in r for v in ids[:3]) for r in rows):
                status, matched = "confirmed", api
                break
        if not status:
            # no change at all in the app of any confirmed write
            err = False
            if i is not None:
                for api in apis:
                    req = find_request(blocks, i, api, st)
                    if req is None:
                        err = True
            status = "not_confirmed"
            reason = ("request not found in api_calls.jsonl — a detector error is likely"
                      if err else
                      "the request reached the server, but the state did not change "
                      "(idempotent or rejected)")
        out.append(dict(base, status=status, reason=reason, matched_api=matched,
                        n_diff_rows=ndiff))
    with open("partial_confirmation.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print("| group | N | confirmed | not_confirmed | undeterminable_partial |")
    print("|---|--:|--:|--:|--:|")
    for g in ("legacy", "modern"):
        gg = [r for r in out if r["group"] == g]
        c = collections.Counter(r["status"] for r in gg)
        print(f"| {g} | {len(gg)} | {c['confirmed']} | {c['not_confirmed']} | "
              f"{c['undeterminable_partial']} |")
    print("\nreasons not_confirmed:",
          dict(collections.Counter(r["reason"] for r in out if r["status"] == "not_confirmed")))


if __name__ == "__main__":
    main()
