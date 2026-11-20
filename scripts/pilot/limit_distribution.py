#!/usr/bin/env python3
"""Step 3b: outcome per continuation and the length of the historical recovery of the
same episode (blocks after the study block in the source trajectory)."""
import csv, json, glob, sys, statistics
sys.path.insert(0, "replay_root"); sys.path.insert(0, ".")
import appworld_audit as A

eps = {(r["task_id"], r["block"]): r for r in csv.DictReader(open("episodes.csv"))}
hist = {}
for k, ep in eps.items():
    bl = A.parse_blocks(__import__("pathlib").Path(ep["path"]) / "logs" / "environment_io.md")
    pos = [b["index"] for b in bl].index(int(ep["block"]))
    tail = bl[pos + 1:]
    hist[k] = dict(total=len(bl), after=len(tail),
                   hist_complete=int(any("complete_task" in b["code"] for b in tail)))
rows = []
for f in sorted(glob.glob("pilot_results_*.json")) + sorted(glob.glob("pilot_E/pilot_results_E*.json")):
    for r in json.load(open(f)):
        if not r.get("usable"):
            continue
        h = hist[(r["task_id"], r["block"])]
        rows.append(dict(condition=r["condition"], task_id=r["task_id"], block=r["block"],
                         arm=r["arm"], outcome=r["outcome"], n_steps=r["n_steps"],
                         evaluator=r.get("evaluator"), hist_blocks_after=h["after"],
                         hist_total_blocks=h["total"], hist_reached_complete=h["hist_complete"]))
w = csv.DictWriter(open("reports/pilot_closeout/limit_distribution.csv", "w", newline=""), fieldnames=list(rows[0]))
w.writeheader(); w.writerows(rows)
per_ep = sorted(v["after"] for v in hist.values())
q = lambda p: per_ep[min(len(per_ep) - 1, int(round(p * (len(per_ep) - 1))))]
print("episodes:", len(per_ep), "hist blocks after study block:", per_ep)
print("median", statistics.median(per_ep), "p75", q(.75), "p90", q(.9), "p95", q(.95), "max", per_ep[-1])
print("hist episodes that reached complete_task:", sum(v["hist_complete"] for v in hist.values()))
import collections
for c in "ABCDE":
    g = [r for r in rows if r["condition"] == c]
    if g:
        print(c, dict(collections.Counter(r["outcome"] for r in g)),
              "limit-hit eps with hist>12:", sum(1 for r in g if r["outcome"] == "limit" and r["hist_blocks_after"] > 12),
              "/", sum(1 for r in g if r["outcome"] == "limit"))
