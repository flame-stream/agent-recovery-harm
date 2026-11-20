#!/usr/bin/env python3
"""Compact digest of the blind table for manual labelling."""
import csv, json, re, sys, textwrap
csv.field_size_limit(10**9)
lo, hi = int(sys.argv[1]), int(sys.argv[2])
KEEP = ("product_id", "quantity", "gift_wrap_quantity", "name", "path", "amount",
        "email_id", "email_thread_id", "order_id", "status", "street_address")


def brief(rows):
    out = []
    for r in rows:
        if r.startswith("...more"):
            out.append(r); continue
        try:
            d = json.loads(r)
        except Exception:
            out.append(r[:70]); continue
        kv = [f"{k}={d[k]}" for k in KEEP if k in d]
        if not kv:
            kv = [f"{k}={str(v)[:24]}" for k, v in list(d.items())[:4] if k != "record_hash"]
        out.append("{" + ",".join(kv) + "}")
    return " ".join(out)[:220]


def tabs(js):
    d = json.loads(js or "{}")
    return [(t.split(".")[-1], v) for t, v in sorted(d.items())]


for r in csv.DictReader(open("blind_labels_random_input.csv")):
    s = int(r["slot"])
    if not (lo <= s <= hi):
        continue
    net = tabs(r["net_B_to_C"])
    if not net:
        continue
    print("=" * 98)
    print(f"SLOT {s} | {r['task_id']} | write-calls after B: {r['n_writes_after_B']}")
    print(textwrap.fill("TASK: " + r["instruction"], 96, subsequent_indent="   "))
    made = tabs(r["made_by_failed_block"])
    if made:
        print("  the failed block created:")
        for t, v in made[:4]:
            print(f"    {t}: +{v['n_added']} -{v['n_removed']} {brief(v['added'])[:150]}")
    print("  NET CHANGE B→C:")
    for t, v in net[:6]:
        print(f"    {t}: +{v['n_added']} -{v['n_removed']}")
        if v["added"]:
            print(f"       + {brief(v['added'])}")
        if v["removed"]:
            print(f"       - {brief(v['removed'])}")
