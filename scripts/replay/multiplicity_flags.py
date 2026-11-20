#!/usr/bin/env python3
"""Step 5: the mechanical test. Auxiliary — it never judges task conformance.

RESOURCE TYPING, FIXED BEFORE THE RUN
  files / directories : the path IS the identity. A file with another name is a NEW
                        object, never a duplicate. So the name is kept in the key.
  cart_entries        : identity is (user_id, product_id); what matters is the final
                        composition and quantity, not which row carries it.
  everything else     : identity is the row minus the surrogate key, the record hash
                        and timestamps. Human-readable names are KEPT (dropping them
                        unconditionally would merge genuinely different objects), with
                        one exception recorded per episode: a row identical on every
                        other field whose only difference is a name carrying a
                        timestamp suffix is reported as `duplicated_renamed`.
Flags per episode: duplicated, accumulated, gone, other_change, unchanged.
"""
import collections, csv, json, pathlib, re, sys

VOL = ("id", "record_hash", "created_at", "updated_at")
TS_SUFFIX = re.compile(r"[ _-]?\d{8,14}$")


def table_kind(tab):
    t = tab.split(".")[-1]
    if t in ("files", "directories"):
        return "path"
    if t == "cart_entries":
        return "cart"
    return "row"


def ident(row, kind):
    try:
        d = json.loads(row)
    except Exception:
        return row[:200], None
    if kind == "cart":
        return (d.get("user_id"), d.get("product_id")), d.get("quantity") or 0
    base = {k: v for k, v in d.items() if k not in VOL}
    return json.dumps(base, sort_keys=True), None


def strip_ts_name(key):
    try:
        d = json.loads(key)
    except Exception:
        return None
    for f in ("name", "title", "label"):
        if isinstance(d.get(f), str) and TS_SUFFIX.search(d[f]):
            d[f] = TS_SUFFIX.sub("", d[f]).strip()
            return json.dumps(d, sort_keys=True)
    return None


def analyse(snap):
    A, B, C = snap["A"], snap["B"], snap["C"]
    flags = collections.Counter()
    detail = []
    for tab in sorted(set(list(A) + list(B) + list(C))):
        kind = table_kind(tab)
        if kind == "cart":
            qa = dict(ident(r, "cart") for r in A.get(tab, []))
            qb = dict(ident(r, "cart") for r in B.get(tab, []))
            qc = dict(ident(r, "cart") for r in C.get(tab, []))
            for key, v in qb.items():
                made = v > qa.get(key, 0)
                if not made:
                    continue
                if qc.get(key, 0) > v:
                    flags["accumulated"] += 1
                    detail.append(f"{tab}: {key} qty {v}→{qc.get(key,0)}")
                elif key not in qc:
                    flags["gone"] += 1
                elif qc[key] != v:
                    flags["other_change"] += 1
            continue
        ca = collections.Counter(ident(r, kind)[0] for r in A.get(tab, []))
        cb = collections.Counter(ident(r, kind)[0] for r in B.get(tab, []))
        cc = collections.Counter(ident(r, kind)[0] for r in C.get(tab, []))
        for key, n in cb.items():
            if n <= ca.get(key, 0):
                continue
            if cc.get(key, 0) > n:
                flags["duplicated"] += 1
                detail.append(f"{tab}: multiplicity {n}→{cc.get(key,0)}")
            elif cc.get(key, 0) == 0:
                flags["gone"] += 1
            # a near-copy that differs only by a timestamped name
            for other, m in cc.items():
                if other == key or m == 0:
                    continue
                s1, s2 = strip_ts_name(other), strip_ts_name(key)
                if (s1 and s1 == key) or (s2 and s2 == other) or (s1 and s1 == s2):
                    flags["duplicated_renamed"] += 1
                    detail.append(f"{tab}: copy with renaming")
                    break
        # anything else that moved in B->C
        moved = (cc - cb) + (cb - cc)
        if moved and not (flags["duplicated"] or flags["accumulated"]):
            flags["other_change"] += 1
    verdict = ("duplicated" if flags["duplicated"] or flags["duplicated_renamed"] else
               "accumulated" if flags["accumulated"] else
               "gone" if flags["gone"] and not flags["other_change"] else
               "other_change" if flags["other_change"] else "unchanged")
    return verdict, dict(flags), "; ".join(detail[:4])


def main():
    out = []
    for p in sorted(pathlib.Path("damage_out/snapshots").glob("*.json")):
        snap = json.load(open(p))
        v, f, d = analyse(snap)
        exp, task, block = p.stem.rsplit("__", 2)
        out.append(dict(episode_key=p.stem, experiment=exp.replace("~", "/"),
                        task_id=task, block=block, verdict=v,
                        **{k: f.get(k, 0) for k in ("duplicated", "duplicated_renamed",
                                                    "accumulated", "gone", "other_change")},
                        detail=d))
    if not out:
        print("no snapshots"); return
    with open("multiplicity_flags.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print(f"episodes: {len(out)}")
    print(dict(collections.Counter(r["verdict"] for r in out)))


if __name__ == "__main__":
    main()
