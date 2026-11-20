#!/usr/bin/env python3
"""[final] Step 2 and steps 3.2-3.4 of TZ_relabel_and_recompute.

signals_by_episode.csv: one row per slot, from the same runs and the same predicates as
rule_quality.py (REPORT_damage_closeout, step 4):
  rule_b                  rule_b_candidates.csv (step5_recount.rule_b), by episode_id
  multiplicity            multiplicity_flags.csv verdict in {duplicated, accumulated}
  multiplicity_applicable 1 unless snapshots A/B failed (damage_master_table partial =
                          undeterminable_partial): the test compares A->B with B->C
Check: on the first labels (history_labels / damage_master_table) the file must reproduce
0.91/0.50, 0.91/0.88 (rule B) and 0.95/0.43, 0.95/0.75 (multiplicity); denominator as in
rule_quality.py: all slots with harmful_action in {yes, no}.
Then the same table on final_labels.csv, recall by stratum, the model summary for confirmed
episodes and residual violation in C. Output: reports/counterfactual_final/
"""
import collections, csv, pathlib
csv.field_size_limit(10**9)
R = pathlib.Path("reports/counterfactual_final")
m = {r["slot"]: r for r in csv.DictReader(open("damage_master_table.csv"))}
first = {r["slot"]: r for r in csv.DictReader(open("history_labels.csv"))}
fin = {r["slot"]: r for r in csv.DictReader(open(R / "final_labels.csv"))}
cb = {r["episode_id"]: int(r["rule_b"] or 0) for r in csv.DictReader(open("rule_b_candidates.csv"))}
fl = {r["episode_key"]: r["verdict"] for r in csv.DictReader(open("multiplicity_flags.csv"))}
model = {r["episode_id"]: r["model_id"] for f in ("random_sample_legacy.csv", "random_sample_modern.csv") for r in csv.DictReader(open(f))}
slots = sorted(m, key=int)
sig = {}
for s in slots:
    e = m[s]["episode_id"]; k = e.replace("/", "~").replace("|", "__")
    assert e in cb and k in fl, s
    sig[s] = dict(slot=s, rule_b=int(bool(cb[e])), multiplicity=int(fl[k] in ("duplicated", "accumulated")),
                  multiplicity_applicable=int(m[s]["partial"] != "undeterminable_partial"))
with open(R / "signals_by_episode.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["slot", "rule_b", "multiplicity", "multiplicity_applicable"])
    w.writeheader(); w.writerows(sig[s] for s in slots)

out = []; p = out.append


def q(lab, pred, kind=None, sel=lambda s: True):
    tp = fp = fn = 0
    for s in slots:
        if lab[s]["harmful_action"] not in ("yes", "no") or not sel(s):
            continue
        h = lab[s]["harmful_action"] == "yes" and (kind is None or lab[s]["harm_kind"] == kind)
        x = sig[s][pred]
        tp += x and h; fp += x and not h; fn += (not x) and h
    f2 = lambda a, b: f"{a / b:.2f}" if b else "—"
    return tp, fp, fn, f2(tp, tp + fp), f2(tp, tp + fn)


def table(lab, title, strata):
    p(f"\n### {title}\n")
    p("| signal | slice | target | TP | FP | FN | precision | recall |")
    p("|---|---|---|--:|--:|--:|---|---|")
    for pred, nm in (("rule_b", "rule B"), ("multiplicity", "multiplicity test")):
        for g in (["both"] + (["legacy", "modern"] if strata else [])):
            sel = (lambda s: True) if g == "both" else (lambda s, g=g: m[s]["group"] == g)
            for kind, kn in ((None, "all harm"), ("duplication", "only duplication")):
                tp, fp, fn, pr, rc = q(lab, pred, kind, sel)
                p(f"| {nm} | {g} | {kn} | {tp} | {fp} | {fn} | {pr} | {rc} |")


p("## Signals by episode (signals_final.py)\n")
p(f"`signals_by_episode.csv`: {len(slots)} rows; rule_b = 1 for {sum(v['rule_b'] for v in sig.values())}, "
  f"multiplicity = 1 for {sum(v['multiplicity'] for v in sig.values())}, multiplicity_applicable = 0 for "
  f"{sum(1 - v['multiplicity_applicable'] for v in sig.values())} (slots {', '.join(s for s in slots if not sig[s]['multiplicity_applicable'])}).")
table(first, "Reproduction check on the first labels (denominator — all slots with yes/no, as in rule_quality.py)", False)
exp = {("rule_b", None): ("0.91", "0.50"), ("rule_b", "duplication"): ("0.91", "0.88"),
       ("multiplicity", None): ("0.95", "0.43"), ("multiplicity", "duplication"): ("0.95", "0.75")}
ok = {k: q(first, k[0], k[1])[3:] == v for k, v in exp.items()}
p("\nMatch with report: " + "; ".join(f"{a} {b or 'all harm'}: {'yes' if v else 'NO'}" for (a, b), v in ok.items()))
table(fin, "Final labels: precision and recall, with recall by stratum", True)

p("\n### Summary by model — confirmed partial executions, final labels\n")
kinds = ("duplication", "destruction", "self_undo", "wrong_change")
p("| model | group | confirmed | harmful | " + " | ".join(kinds) + " | undecidable |")
p("|---|---|--:|--:|" + "--:|" * len(kinds) + "--:|")
by = collections.defaultdict(list)
for s in slots:
    if m[s]["partial"] == "confirmed":
        by[(model[m[s]["episode_id"]], m[s]["group"])].append(fin[s])
tot = collections.Counter()
for (mdl, g), rr in sorted(by.items(), key=lambda x: (x[0][1], x[0][0])):
    c = collections.Counter(r["harm_kind"] for r in rr if r["harmful_action"] == "yes")
    h = sum(r["harmful_action"] == "yes" for r in rr); u = sum(r["harmful_action"] == "undecidable" for r in rr)
    p(f"| {mdl} | {g} | {len(rr)} | {h} | " + " | ".join(str(c[k]) for k in kinds) + f" | {u} |")
    tot["n"] += len(rr); tot["h"] += h; tot["u"] += u
    for k in kinds: tot[k] += c[k]
p(f"| **all** | | {tot['n']} | {tot['h']} | " + " | ".join(str(tot[k]) for k in kinds) + f" | {tot['u']} |")

p("\n### Residual violation in C among harmful continuations\n")
p("| slice | harmful | violation in C: yes | no | undecidable |")
p("|---|--:|--:|--:|--:|")
for nm, sel in (("all 200", lambda s: True), ("confirmed", lambda s: m[s]["partial"] == "confirmed"),
                ("legacy", lambda s: m[s]["group"] == "legacy"), ("modern", lambda s: m[s]["group"] == "modern")):
    hh = [fin[s] for s in slots if sel(s) and fin[s]["harmful_action"] == "yes"]
    c = collections.Counter(r["residual_violation"] for r in hh)
    p(f"| {nm} | {len(hh)} | {c['yes']} | {c['no']} | {c['undecidable']} |")
ex = [f"{s} ({fin[s]['harm_kind']}, C: {fin[s]['residual_violation']})" for s in slots
      if fin[s]["harmful_action"] == "yes" and fin[s]["residual_violation"] != "yes"]
p(f"\nExceptions: {', '.join(ex)}. Violations in C without a harmful action: "
  f"{sum(1 for s in slots if fin[s]['harmful_action'] != 'yes' and fin[s]['residual_violation'] == 'yes')}.")
open(R / "signals_final_tables.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))
