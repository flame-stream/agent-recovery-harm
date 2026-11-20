#!/usr/bin/env python3
"""Step 3: the one table every percentage in the report comes from."""
import collections, csv, json, math, random, statistics

Y, N, U = "yes", "no", "undecidable"


def wilson(k, n, z=1.96):
    if not n: return (0.0, 0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def boot(rows, field, reps=4000, seed=17):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["source_run"]].append(r)
    runs = list(by)
    rnd = random.Random(seed)
    vals = []
    for _ in range(reps):
        eps = [e for _ in range(len(runs)) for e in by[runs[rnd.randrange(len(runs))]]]
        dec = [e for e in eps if e[field] in (Y, N)]
        if dec:
            vals.append(sum(1 for e in dec if e[field] == Y) / len(dec))
    vals.sort()
    return (statistics.mean(vals), vals[int(.025 * len(vals))], vals[int(.975 * len(vals))]) \
        if vals else (0, 0, 0)


def main():
    csv.field_size_limit(10**9)
    lab = {r["slot"]: r for r in csv.DictReader(open("history_labels.csv"))}
    pc = {r["slot"]: r for r in csv.DictReader(open("partial_confirmation.csv"))}
    rows = []
    for s, r in lab.items():
        p = pc[s]
        rows.append(dict(slot=s, episode_id=r["episode_id"], group=r["group"],
                         experiment=r["experiment"], source_run=p["source_run"],
                         task_id=r["task_id"], partial=p["status"],
                         partial_reason=p["reason"], harmful_action=r["harmful_action"],
                         residual_violation=r["residual_violation"],
                         harm_kind=r["harm_kind"]))
    with open("damage_master_table.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    print("## Source table\n")
    print("| group | N | undeterminable_partial | confirmed | not_confirmed | "
          "among confirmed: undeterminable_harm | H(action) | H(residual) | intersection |")
    print("|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for g in ("legacy", "modern"):
        gg = [r for r in rows if r["group"] == g]
        c = [r for r in gg if r["partial"] == "confirmed"]
        uh = sum(1 for r in c if r["harmful_action"] == U)
        ha = sum(1 for r in c if r["harmful_action"] == Y)
        hr = sum(1 for r in c if r["residual_violation"] == Y)
        both = sum(1 for r in c if r["harmful_action"] == Y and r["residual_violation"] == Y)
        print(f"| {g} | {len(gg)} | "
              f"{sum(1 for r in gg if r['partial']=='undeterminable_partial')} | {len(c)} | "
              f"{sum(1 for r in gg if r['partial']=='not_confirmed')} | {uh} | {ha} | {hr} | {both} |")

    print("\n## Share of harm among confirmed partial executions\n")
    print("| group | denominator (confirmed, decidable) | H | observed share | "
          "bootstrap over runs | Wilson | bounds H/C … (H+U)/C |")
    print("|---|--:|--:|---|---|---|---|")
    for g in ("legacy", "modern"):
        c = [r for r in rows if r["group"] == g and r["partial"] == "confirmed"]
        dec = [r for r in c if r["harmful_action"] in (Y, N)]
        H = sum(1 for r in c if r["harmful_action"] == Y)
        Uu = len(c) - len(dec)
        m, lo, hi = boot(c, "harmful_action")
        _, wl, wh = wilson(H, len(dec))
        print(f"| {g} | {len(dec)} | {H} | **{100*H/len(dec):.1f} %** | "
              f"{100*m:.1f} % [{100*lo:.1f}, {100*hi:.1f}] | [{100*wl:.1f}, {100*wh:.1f}] | "
              f"{100*H/len(c):.1f} % … {100*(H+Uu)/len(c):.1f} % |")
    sub = [r for r in rows if r["group"] == "modern" and r["partial"] == "confirmed"
           and not r["experiment"].startswith("rooagi")]
    dec = [r for r in sub if r["harmful_action"] in (Y, N)]
    H = sum(1 for r in sub if r["harmful_action"] == Y)
    if dec:
        print(f"| modern without rooagi | {len(dec)} | {H} | {100*H/len(dec):.1f} % | — | — | "
              f"{100*H/len(sub):.1f} % … {100*(H+len(sub)-len(dec))/len(sub):.1f} % |")

    print("\n## Intersection of the two quantities and an empty final diff\n")
    a = [r for r in rows if r["harmful_action"] == Y]
    print(f"- episodes with a harmful action in history: **{len(a)}**")
    print(f"- of them without a residual violation in C: "
          f"{sum(1 for r in a if r['residual_violation'] != Y)}")
    print(f"- residual violations without a harmful action after B: "
          f"{sum(1 for r in rows if r['residual_violation']==Y and r['harmful_action']!=Y)}")


if __name__ == "__main__":
    main()
