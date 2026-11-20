#!/usr/bin/env python3
"""Step 4: rule B and the mechanical test, by harm kind."""
import collections, csv

Y, N = "yes", "no"
csv.field_size_limit(10**9)
m = {r["slot"]: r for r in csv.DictReader(open("damage_master_table.csv"))}
lab = {r["slot"]: r for r in csv.DictReader(open("history_labels.csv"))}
cb = {r["episode_id"]: int(r["rule_b"] or 0) for r in csv.DictReader(open("rule_b_candidates.csv"))}
fl = {r["episode_key"]: r["verdict"] for r in csv.DictReader(open("multiplicity_flags.csv"))}


def flag(eid):
    return fl.get(eid.replace("/", "~").replace("|", "__")) in ("duplicated", "accumulated")


def quality(pred, rows, kind=None):
    tp = fp = fn = 0
    for r in rows:
        h = r["harmful_action"] == Y
        if kind:
            h = h and lab[r["slot"]]["harm_kind"] == kind
        p = pred(r["episode_id"])
        if p and h: tp += 1
        elif p and not h: fp += 1
        elif (not p) and h: fn += 1
    pr = tp / (tp + fp) if tp + fp else None
    rc = tp / (tp + fn) if tp + fn else None
    return tp, fp, fn, pr, rc


def fmt(x):
    return f"{x:.2f}" if x is not None else "—"


for name, pred in (("rule B", lambda e: bool(cb.get(e))),
                   ("mechanical test", flag)):
    print(f"\n## {name}\n")
    print("| group | target | TP | FP | FN | precision | recall |")
    print("|---|---|--:|--:|--:|---|---|")
    for g in ("legacy", "modern", "both"):
        rows = [r for r in m.values() if (g == "both" or r["group"] == g)
                and r["harmful_action"] in (Y, N)]
        for kind, lbl in ((None, "all harm"), ("duplication", "only duplication")):
            tp, fp, fn, pr, rc = quality(pred, rows, kind)
            print(f"| {g} | {lbl} | {tp} | {fp} | {fn} | {fmt(pr)} | {fmt(rc)} |")

print("\n## Share of duplication in total harm\n")
print("| group | harm total | duplication | share |")
print("|---|--:|--:|---|")
for g in ("legacy", "modern", "both"):
    rows = [r for r in m.values() if (g == "both" or r["group"] == g)
            and r["harmful_action"] == Y]
    d = sum(1 for r in rows if lab[r["slot"]]["harm_kind"] == "duplication")
    print(f"| {g} | {len(rows)} | {d} | {100*d/len(rows):.0f} % |")
