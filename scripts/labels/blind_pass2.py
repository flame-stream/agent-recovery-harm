#!/usr/bin/env python3
"""Step 6 agreement: a second pass over 40 episodes.

Not a second person: the same annotator, but the conclusion is drawn anew and mechanically from
snapshots by the same fixed rules, without referring to the first pass.
This is an upper bound on consistency, not independent agreement between two people.
"""
import collections, csv, json, pathlib, random

SEED, N = 77, 40
VOL = ("id", "record_hash", "created_at", "updated_at")


def key(r):
    d = json.loads(r)
    return json.dumps({k: v for k, v in d.items() if k not in VOL}, sort_keys=True)


def cartmap(rows):
    m = {}
    for r in rows:
        d = json.loads(r)
        m[(d.get("user_id"), d.get("product_id"))] = d.get("quantity") or 0
    return m


def derive(snap):
    """duplication: something present in B appears more often / in larger quantity in C.
       destruction: a row present in A and in B is absent in C."""
    dup = dest = False
    A, B, C = snap["A"], snap["B"], snap["C"]
    for t in set(list(B) + list(C)):
        if t.endswith("cart_entries"):
            ma, mb, mc = cartmap(A.get(t, [])), cartmap(B.get(t, [])), cartmap(C.get(t, []))
            for k, v in mb.items():
                if mc.get(k, 0) > v:
                    dup = True
                if k in ma and k not in mc:
                    dest = True
            continue
        ca = collections.Counter(key(x) for x in A.get(t, []))
        cb = collections.Counter(key(x) for x in B.get(t, []))
        cc = collections.Counter(key(x) for x in C.get(t, []))
        for k, n in cb.items():
            if cc.get(k, 0) > n:
                dup = True
            if ca.get(k, 0) and cc.get(k, 0) == 0:
                dest = True
    return dup, dest


def main():
    csv.field_size_limit(10**9)
    lab = {r["slot"]: r for r in csv.DictReader(open("blind_labels_random.csv"))}
    mp = {r["slot"]: r for r in csv.DictReader(open("blind_labels_random_map.csv"))}
    bad = set(json.load(open("instrument_undecidable.json")))
    slots = sorted(lab, key=int)
    sample = sorted(random.Random(SEED).sample(slots, N), key=int)
    rows, agree = [], 0
    for s in sample:
        eid = mp[s]["episode_id"]
        p = pathlib.Path("damage_out/snapshots") / (eid.replace("/", "~").replace("|", "__") + ".json")
        if eid in bad or not p.exists():
            v2 = "undecidable"
        else:
            dup, dest = derive(json.load(open(p)))
            v2 = "yes" if (dup or dest) else "no"
        ok = int(v2 == lab[s]["new_harm_after_B"])
        agree += ok
        rows.append(dict(slot=s, task_id=lab[s]["task_id"], pass1=lab[s]["new_harm_after_B"],
                         pass2=v2, kind=lab[s]["harm_kind"], agree=ok,
                         basis=lab[s]["basis"][:90]))
    with open("blind_labels_agreement.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"consistency on {N} episodes (seed={SEED}): {agree}/{N} = {100.0*agree/N:.0f} %")
    for r in rows:
        if not r["agree"]:
            print(f"  slot {r['slot']:>4} {r['task_id']:<12} pass1={r['pass1']:<5} "
                  f"pass2={r['pass2']:<5} | {r['basis']}")


if __name__ == "__main__":
    main()
