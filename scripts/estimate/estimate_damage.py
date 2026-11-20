#!/usr/bin/env python3
"""Step 7: the two damage quantities per group, with bounds and intervals.

Main interval: cluster bootstrap over source runs, episodes weighted equally.
Wilson: supplementary. Bounds: H/N (all undecidables benign) to (H+U)/N (all harmful).
"""
import collections, csv, json, math, random, statistics, sys
csv.field_size_limit(10**9)


def wilson(k, n, z=1.96):
    if not n: return (0.0, 0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def boot(rows, field, reps=4000, seed=17):
    """Cluster bootstrap over source runs; every episode carries equal weight."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["source_run"]].append(r)
    runs = list(by)
    if not runs:
        return (0.0, 0.0, 0.0)
    rnd = random.Random(seed)
    vals = []
    for _ in range(reps):
        pick = [by[runs[rnd.randrange(len(runs))]] for _ in range(len(runs))]
        eps = [e for g in pick for e in g]
        dec = [e for e in eps if e[field] in ("yes", "no")]
        if dec:
            vals.append(sum(1 for e in dec if e[field] == "yes") / len(dec))
    vals.sort()
    if not vals:
        return (0.0, 0.0, 0.0)
    return (statistics.mean(vals), vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))])


def main():
    lab = list(csv.DictReader(open("blind_labels_random.csv")))
    mp = {r["slot"]: r for r in csv.DictReader(open("blind_labels_random_map.csv"))}
    reg = {r["episode_id"]: r for r in csv.DictReader(open("episode_registry.csv"))}
    for r in lab:
        m = mp[r["slot"]]
        r.update(group=m["group"], experiment=m["experiment"], model_id=m["model_id"],
                 source_run=reg[m["episode_id"]]["source_run"], episode_id=m["episode_id"])

    print("## Two harm quantities by group\n")
    for field, name in (("new_harm_after_B", "new harmful action after B"),
                        ("residual_violation_in_C", "residual violation in C")):
        print(f"### {name}\n")
        print("| group | N | determinable | H | U (undecidable) | share among determinable "
              "(bootstrap over runs) | Wilson | bounds H/N … (H+U)/N |")
        print("|---|--:|--:|--:|--:|---|---|---|")
        for g in ("legacy", "modern"):
            gg = [r for r in lab if r["group"] == g]
            dec = [r for r in gg if r[field] in ("yes", "no")]
            H = sum(1 for r in gg if r[field] == "yes")
            U = len(gg) - len(dec)
            m, lo, hi = boot(gg, field)
            _, wl, wh = wilson(H, len(dec))
            print(f"| {g} | {len(gg)} | {len(dec)} | {H} | {U} | "
                  f"{100*m:.1f} % [{100*lo:.1f}, {100*hi:.1f}] | "
                  f"[{100*wl:.1f}, {100*wh:.1f}] | "
                  f"{100*H/len(gg):.1f} % … {100*(H+U)/len(gg):.1f} % |")
        # modern without the dominant configuration
        gg = [r for r in lab if r["group"] == "modern"]
        dom = collections.Counter(r["experiment"] for r in gg).most_common(1)[0][0]
        sub = [r for r in gg if r["experiment"] != dom]
        dec = [r for r in sub if r[field] in ("yes", "no")]
        H = sum(1 for r in sub if r[field] == "yes")
        if dec:
            m, lo, hi = boot(sub, field)
            print(f"| modern without {dom.split('_')[0]} | {len(sub)} | {len(dec)} | {H} | "
                  f"{len(sub)-len(dec)} | {100*m:.1f} % [{100*lo:.1f}, {100*hi:.1f}] | — | "
                  f"{100*H/len(sub):.1f} % … {100*(H+len(sub)-len(dec))/len(sub):.1f} % |")
        print()

    # rule B quality against the blind labels
    cand = {r["episode_id"]: int(r["rule_b"] or 0)
            for r in csv.DictReader(open("rule_b_candidates.csv"))}
    print("## Quality of Rule B against blind labels (on random samples)\n")
    print("| group | TP | FP | FN | TN | precision | recall | P(harm｜candidate) | P(harm｜not candidate) |")
    print("|---|--:|--:|--:|--:|---|---|---|---|")
    for g in ("legacy", "modern", "both"):
        gg = [r for r in lab if (g == "both" or r["group"] == g)
              and r["new_harm_after_B"] in ("yes", "no")]
        tp = sum(1 for r in gg if cand.get(r["episode_id"]) and r["new_harm_after_B"] == "yes")
        fp = sum(1 for r in gg if cand.get(r["episode_id"]) and r["new_harm_after_B"] == "no")
        fn = sum(1 for r in gg if not cand.get(r["episode_id"]) and r["new_harm_after_B"] == "yes")
        tn = sum(1 for r in gg if not cand.get(r["episode_id"]) and r["new_harm_after_B"] == "no")
        pr = f"{tp/(tp+fp):.2f}" if tp + fp else "—"
        rc = f"{tp/(tp+fn):.2f}" if tp + fn else "—"
        pc = f"{100*tp/(tp+fp):.0f} %" if tp + fp else "—"
        pn = f"{100*fn/(fn+tn):.0f} %" if fn + tn else "—"
        print(f"| {g} | {tp} | {fp} | {fn} | {tn} | {pr} | {rc} | {pc} | {pn} |")


if __name__ == "__main__":
    main()
