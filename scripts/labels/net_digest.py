#!/usr/bin/env python3
"""Corrected net B->C view: small tables from full A/B/C rows, LARGE tables from the
stored BC deltas. The earlier pass compared only the full-row copies, so changes in any
table over 2000 rows (gmail.emails, amazon.orders, file_system.files ...) were invisible.
"""
import collections, csv, json, pathlib, sys, textwrap
csv.field_size_limit(10**9)
VOL = ("id", "record_hash", "created_at", "updated_at")
SPEC = {}


def instr(t):
    if t not in SPEC:
        p = pathlib.Path("data/tasks") / t / "specs.json"
        SPEC[t] = json.load(open(p)).get("instruction", "") if p.exists() else ""
    return SPEC[t]


def sub(r):
    try:
        d = json.loads(r)
    except Exception:
        return "TRUNC:" + r[:200]
    return json.dumps({k: v for k, v in d.items() if k not in VOL}, sort_keys=True)


def short(js, n=4):
    try:
        d = json.loads(js)
    except Exception:
        return js[:110]
    return ", ".join(f"{k}={str(v)[:30]}" for k, v in list(d.items())[:n])


def net(snap):
    """[(table, added_substances, removed_substances, from_delta)]"""
    out = []
    big = snap.get("big_table_deltas", {})
    for t in sorted(set(list(snap["B"]) + list(snap["C"])) - set(big)):
        cb = collections.Counter(sub(x) for x in snap["B"].get(t, []))
        cc = collections.Counter(sub(x) for x in snap["C"].get(t, []))
        a, r = list((cc - cb).elements()), list((cb - cc).elements())
        if a or r:
            out.append((t, a, r, False))
    for t, d in sorted(big.items()):
        a = [sub(x) for x in d["BC_added"]]
        r = [sub(x) for x in d["BC_removed"]]
        a2 = [x for x in a if x not in r]
        r2 = [x for x in r if x not in a]
        if a2 or r2:
            out.append((t, a2, r2, True))
    return out


def main():
    only = set(sys.argv[1:]) or None
    mp = {r["slot"]: r for r in csv.DictReader(open("blind_labels_random_map.csv"))}
    inp = {r["slot"]: r for r in csv.DictReader(open("blind_labels_random_input.csv"))}
    for s in sorted(mp, key=int):
        if only and s not in only:
            continue
        k = mp[s]["episode_id"].replace("/", "~").replace("|", "__")
        p = pathlib.Path("damage_out/snapshots") / f"{k}.json"
        if not p.exists():
            continue
        snap = json.load(open(p))
        at_A = {t: collections.Counter(sub(x) for x in v) for t, v in snap["A"].items()}
        rows = net(snap)
        if not rows:
            continue
        print("=" * 98)
        print(f"SLOT {s} | {inp[s]['task_id']}")
        print(textwrap.fill("TASK: " + instr(inp[s]["task_id"]), 96, subsequent_indent="   "))
        for t, a, r, isbig in rows:
            tag = " [from the delta of a large table]" if isbig else ""
            print(f"  {t.split('.')[-1]}: +{len(a)} -{len(r)}{tag}")
            ca = collections.Counter(a)
            for x, n in list(ca.items())[:3]:
                mark = "  [SUCH A ROW ALREADY EXISTED in B]" if snap["B"].get(t) and any(
                    sub(y) == x for y in snap["B"][t]) else ""
                print(f"     +{n} {short(x)}{mark}")
            for x in r[:3]:
                mark = "  [EXISTED BEFORE A]" if at_A.get(t, {}).get(x) else ""
                print(f"     -1 {short(x)}{mark}")


if __name__ == "__main__":
    main()
