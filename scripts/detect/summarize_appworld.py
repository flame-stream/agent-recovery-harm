#!/usr/bin/env python3
"""Tables for steps 1-6 (duplicate leaderboard experiments excluded)."""
import csv, collections, statistics, json, sys
sys.path.insert(0, ".")
from appworld_recovery import is_duplicate

I = lambda r, k: int(r.get(k) or 0)
def pct(a, b): return f"{100.0*a/b:.1f}% ({a}/{b})" if b else "— (0/0)"

RUNS = list(csv.DictReader(open("runs.csv")))
BLOCKS = list(csv.DictReader(open("blocks.csv")))
EP = list(csv.DictReader(open("fail_after_write.csv")))
runs = [r for r in RUNS if not is_duplicate(r["source"], r["experiment"])]
blocks = [r for r in BLOCKS if not is_duplicate(r["source"], r["experiment"])]
ur = [r for r in runs if I(r, "usable")]

print("## T1. Sources and usability of artifacts\n")
print("| source | experiments | runs | full set of files | usable (has blocks and ≥1 non-service call) |")
print("|---|--:|--:|--:|--:|")
for src in ("official", "leaderboard"):
    rs = [r for r in runs if r["source"] == src]
    ex = len({r["experiment"] for r in rs})
    print(f"| {src} | {ex} | {len(rs)} | {pct(len(rs), len(rs))} | {pct(sum(I(r,'usable') for r in rs), len(rs))} |")
print(f"| **total** | {len({(r['source'],r['experiment']) for r in runs})} | {len(runs)} | "
      f"{pct(len(runs), len(runs))} | {pct(sum(I(r,'usable') for r in runs), len(runs))} |")
dupr = [r for r in RUNS if is_duplicate(r["source"], r["experiment"])]
print(f"\nDiscarded before this: {len(dupr)} runs in 28 leaderboard experiments — "
      f"byte-for-byte copies of the official baselines. HAL: does not publish AppWorld traces (0).")
print(f"Unusable among the rest: {pct(len(runs)-len(ur), len(runs))}.\n")

print("\n| agent | model | runs | usable | blocks | median blocks/run |")
print("|---|---|--:|--:|--:|--:|")
by = collections.defaultdict(list)
for r in ur: by[(r["agent"], r["model"])].append(r)
bb = collections.Counter((r["agent"], r["model"]) for r in blocks)
for k, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
    med = statistics.median([I(r, "n_blocks") for r in rs])
    print(f"| {k[0][:34]} | {k[1][:30]} | {len(rs)} | {len(rs)} | {bb[k]} | {med:.0f} |")

print("\n\n## T2. Block classes\n")
print("| slice | blocks | success | fail_before_write | fail_after_write | fail_unknown |")
print("|---|--:|--:|--:|--:|--:|")
def brow(label, rs):
    c = collections.Counter(r["cls"] for r in rs); n = len(rs)
    print(f"| {label} | {n} | {pct(c['success'],n)} | {pct(c['fail_before_write'],n)} | "
          f"{pct(c['fail_after_write'],n)} | {pct(c['fail_unknown'],n)} |")
brow("all blocks", blocks)
ww = [r for r in blocks if I(r, "n_write_sites") > 0]
brow("blocks with ≥1 write call in the code", ww)
fl = [r for r in blocks if r["status"] == "failed"]
brow("failed blocks", fl)
flw = [r for r in fl if I(r, "n_write_sites") > 0]
brow("failed blocks with ≥1 write call", flw)

print("\n### by agent (share of fail_after_write among failed blocks with a write)\n")
print("| agent | failed with write | fail_after_write | fail_unknown |")
print("|---|--:|--:|--:|")
ag = collections.defaultdict(list)
for r in flw: ag[r["agent"]].append(r)
for k, rs in sorted(ag.items(), key=lambda kv: -len(kv[1])):
    c = collections.Counter(r["cls"] for r in rs)
    print(f"| {k[:40]} | {len(rs)} | {pct(c['fail_after_write'],len(rs))} | {pct(c['fail_unknown'],len(rs))} |")
print("\n### by model\n")
print("| model | failed with write | fail_after_write | fail_unknown |")
print("|---|--:|--:|--:|")
mg = collections.defaultdict(list)
for r in flw: mg[r["model"]].append(r)
for k, rs in sorted(mg.items(), key=lambda kv: -len(kv[1])):
    c = collections.Counter(r["cls"] for r in rs)
    print(f"| {k[:34]} | {len(rs)} | {pct(c['fail_after_write'],len(rs))} | {pct(c['fail_unknown'],len(rs))} |")
print("\n### by task difficulty\n")
print("| difficulty | failed with write | fail_after_write |")
print("|---|--:|--:|")
dg = collections.defaultdict(list)
for r in flw: dg[r["difficulty"] or "?"].append(r)
for k in sorted(dg):
    rs = dg[k]; c = collections.Counter(r["cls"] for r in rs)
    print(f"| {k} | {len(rs)} | {pct(c['fail_after_write'],len(rs))} |")

print("\n\n## T3. Recovery after fail_after_write\n")
print(f"episodes: {len(EP)} in {len({r['path'] for r in EP})} runs\n")
CL = ["abandon", "full_rerun", "modified_rerun_overlap", "compensation", "continuation", "state_check", "other"]
print("| slice | n | " + " | ".join(CL) + " |")
print("|---|--:|" + "--:|"*len(CL))
def rrow(label, rs):
    c = collections.Counter(r["primary_class"] for r in rs); n = len(rs)
    print(f"| {label} | {n} | " + " | ".join(pct(c[k], n) for k in CL) + " |")
rrow("**total**", EP)
for k, rs in sorted(collections.Counter(r["agent"] for r in EP).most_common(6)):
    rrow(k[:34], [r for r in EP if r["agent"] == k])
print("\nFlags (not mutually exclusive):\n")
print("| flag | share of episodes |")
print("|---|--:|")
for f in ("full_rerun", "modified_rerun_overlap", "continuation", "state_check", "compensation", "abandon"):
    print(f"| {f} | {pct(sum(I(r,f) for r in EP), len(EP))} |")

print("\n\n## T4. Consequences\n")
print("| indicator | share among 1919 episodes |")
print("|---|--:|")
n = len(EP)
print(f"| a repeated call of an already confirmed write | {pct(sum(I(r,'repeat_confirmed_write') for r in EP), n)} |")
print(f"| of them, a match also by arguments (call text) | {pct(sum(I(r,'repeat_sig_exact') for r in EP), sum(I(r,'repeat_confirmed_write') for r in EP))} |")
print(f"| new effect (the repeat was confirmed to execute) | {pct(sum(I(r,'new_effect') for r in EP), n)} |")
print(f"| the repeated API is a creating one (create_/add_/send_/…) | {pct(sum(I(r,'creating_api') for r in EP), n)} |")
print(f"| candidate for an effect excessive for the task | {pct(sum(I(r,'harmful_candidate') for r in EP), n)} |")
print(f"| of them: the duplicate is visible in the final DB | {pct(sum(1 for r in EP if I(r,'harmful_candidate') and I(r,'dup_insert_in_final_db')), sum(I(r,'harmful_candidate') for r in EP))} |")
print(f"| of them: `transient` (no excess in the final DB) | {pct(sum(I(r,'transient') for r in EP), sum(I(r,'harmful_candidate') for r in EP))} |")

print("\n\n## T5. Denominators and concentration\n")
faw_runs = {r["path"] for r in EP}
print("| denominator | share |")
print("|---|--:|")
print(f"| runs with ≥1 `fail_after_write` | {pct(len(faw_runs), len(ur))} |")
print(f"| `fail_after_write` among all blocks | {pct(sum(1 for r in blocks if r['cls']=='fail_after_write'), len(blocks))} |")
print(f"| … among blocks with ≥1 write | {pct(sum(1 for r in ww if r['cls']=='fail_after_write'), len(ww))} |")
print(f"| … among failed blocks | {pct(sum(1 for r in fl if r['cls']=='fail_after_write'), len(fl))} |")
print(f"| … among failed blocks with ≥1 write | {pct(sum(1 for r in flw if r['cls']=='fail_after_write'), len(flw))} |")
per = collections.Counter(r["path"] for r in EP)
vals = sorted(per.values(), reverse=True); tot = sum(vals)
acc = n50 = n80 = 0
for i, v in enumerate(vals, 1):
    acc += v
    if not n50 and acc >= 0.5*tot: n50 = i
    if not n80 and acc >= 0.8*tot: n80 = i
print(f"| unique runs behind the phenomenon | {len(vals)} of {len(ur)} ({100.0*len(vals)/len(ur):.1f}%) |")
print(f"| runs producing 50 % / 80 % of episodes | {n50} ({100.0*n50/len(vals):.1f}%) / {n80} ({100.0*n80/len(vals):.1f}%) |")
print(f"| episodes per run: median / max | {statistics.median(vals):.0f} / {max(vals)} |")
harm_runs = {r["path"] for r in EP if I(r, "harmful_candidate")}
hr = [r for r in ur if r["path"] in harm_runs]
print(f"\nTasks with ≥1 candidate for a harmful repeat: {len(hr)} runs; "
      f"success by the official evaluator — {pct(sum(I(r,'task_success') for r in hr), len(hr))}. "
      f"For comparison, over all usable runs: {pct(sum(I(r,'task_success') for r in ur), len(ur))}; "
      f"over runs with ≥1 fail_after_write: "
      f"{pct(sum(I(r,'task_success') for r in ur if r['path'] in faw_runs), len(faw_runs))}.")

print("\n\n## T6. Contracts of write APIs on a repeat\n")
print("| API | repeats | rejected by the service | materialized | unknown |")
print("|---|--:|--:|--:|--:|")
by_api = collections.defaultdict(list)
for r in EP:
    if I(r, "repeat_confirmed_write") and r["repeated_api"]:
        by_api[r["repeated_api"]].append(r)
for k, rs in sorted(by_api.items(), key=lambda kv: -len(kv[1]))[:20]:
    rej = sum(1 for r in rs if r["repeat_outcome"].startswith("rejected"))
    mat = sum(1 for r in rs if r["repeat_outcome"] == "materialised")
    unk = len(rs) - rej - mat
    print(f"| `{k}` | {len(rs)} | {pct(rej,len(rs))} | {pct(mat,len(rs))} | {pct(unk,len(rs))} |")
tot_r = sum(len(v) for v in by_api.values())
rej = sum(1 for r in EP if r["repeat_outcome"].startswith("rejected"))
mat = sum(1 for r in EP if r["repeat_outcome"] == "materialised")
print(f"| **all** | {tot_r} | {pct(rej,tot_r)} | {pct(mat,tot_r)} | {pct(tot_r-rej-mat,tot_r)} |")
