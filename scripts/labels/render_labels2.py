#!/usr/bin/env python3
"""Precise per-episode digest from the full snapshots: what the recovery actually
changed relative to B, in terms a task judgement can use."""
import collections, csv, json, pathlib, sys, textwrap
csv.field_size_limit(10**9)
lo, hi = int(sys.argv[1]), int(sys.argv[2])
VOL = ("id", "record_hash", "created_at", "updated_at")
SPEC = {}


def instr(t):
    if t not in SPEC:
        p = pathlib.Path("data/tasks") / t / "specs.json"
        SPEC[t] = json.load(open(p)).get("instruction", "") if p.exists() else ""
    return SPEC[t]


def key(row):
    d = json.loads(row)
    return json.dumps({k: v for k, v in d.items() if k not in VOL}, sort_keys=True), d


def cart_map(rows):
    m = {}
    for r in rows:
        d = json.loads(r)
        m[(d.get("user_id"), d.get("product_id"))] = (d.get("quantity"),
                                                      d.get("gift_wrap_quantity"))
    return m


def short(d, n=5):
    return ", ".join(f"{k}={str(v)[:26]}" for k, v in list(d.items())[:n]
                     if k not in ("record_hash",))


mp = {r["slot"]: r for r in csv.DictReader(open("blind_labels_random_map.csv"))}
inp = {r["slot"]: r for r in csv.DictReader(open("blind_labels_random_input.csv"))}
bad = set(json.load(open("instrument_undecidable.json")))
for slot in range(lo, hi + 1):
    s = str(slot)
    if s not in inp:
        continue
    eid = mp[s]["episode_id"]
    r = inp[s]
    if eid in bad:
        continue
    p = pathlib.Path("damage_out/snapshots") / (eid.replace("/", "~").replace("|", "__") + ".json")
    if not p.exists():
        continue
    snap = json.load(open(p))
    B, C, A = snap["B"], snap["C"], snap["A"]
    lines = []
    for t in sorted(set(list(B) + list(C))):
        if t.endswith("cart_entries"):
            mb, mc, ma = cart_map(B.get(t, [])), cart_map(C.get(t, [])), cart_map(A.get(t, []))
            for k in sorted(set(mb) | set(mc), key=lambda x: str(x)):
                if mb.get(k) == mc.get(k):
                    continue
                lines.append(f"    cart product {k[1]}: was {mb.get(k)} now {mc.get(k)}"
                             f" (before the failed block {ma.get(k)})")
            continue
        cb = collections.Counter(key(x)[0] for x in B.get(t, []))
        cc = collections.Counter(key(x)[0] for x in C.get(t, []))
        add, rem = cc - cb, cb - cc
        for kk, n in list(add.items())[:4]:
            lines.append(f"    +{n} in {t.split('.')[-1]}: {short(json.loads(kk))}"
                         f"{'  [SUCH A ROW ALREADY EXISTED in B]' if cb.get(kk) else ''}")
        for kk, n in list(rem.items())[:4]:
            lines.append(f"    -{n} of {t.split('.')[-1]}: {short(json.loads(kk))}")
        if len(add) > 4 or len(rem) > 4:
            lines.append(f"    ...more {max(0,len(add)-4)} kinds of additions, "
                         f"{max(0,len(rem)-4)} deletions in {t.split('.')[-1]}")
    if not lines:
        continue
    print("=" * 98)
    print(f"SLOT {slot} | {r['task_id']} | write-calls after B: {r['n_writes_after_B']}")
    print(textwrap.fill("TASK: " + instr(r["task_id"]), 96, subsequent_indent="   "))
    print("  WHAT THE RECOVERY CHANGED (B→C):")
    for l in lines[:14]:
        print(l)
