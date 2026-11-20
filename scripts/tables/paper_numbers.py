#!/usr/bin/env python3
"""Every number of the paper, from the files in data/ only (no model, no AppWorld).

    python scripts/tables/paper_numbers.py            # print Tables I-IV and the text numbers
    python scripts/tables/paper_numbers.py --json F   # also write the values to F (used by check.py)

Each value has a key; paper/numbers_trace.csv maps the claims of the paper to these keys.
"""
import argparse, collections, csv, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
D = ROOT / "data"

csv.field_size_limit(10**9)
OUT = {}


def rd(p):
    with open(D / p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def put(key, value):
    OUT[key] = value
    return value


def key_of(eid):
    return eid.replace("/", "~").replace("|", "__")


def pr(a, b):
    return round(a / b, 2) if b else None


# --------------------------------------------------------------------------- inputs
master = {r["slot"]: r for r in rd("sample/damage_master_table.csv")}
pc = {r["slot"]: r for r in rd("sample/partial_confirmation.csv")}
final = {r["slot"]: r for r in rd("labels/final_labels.csv")}
first = {r["slot"]: r for r in rd("labels/first/history_labels.csv")}
second = {}
for f in ("labels/second/relabel_main_slots_completed.csv", "labels/second/relabel_rest_form_completed.csv"):
    for r in rd(f):
        second[r["slot"]] = {k.split("(")[0]: v for k, v in r.items()}
sample = {r["episode_id"]: r for f in ("sample/random_sample_legacy.csv", "sample/random_sample_modern.csv")
          for r in rd(f)}
registry = rd("registry/episode_registry.csv")
runs = rd("corpus/runs.csv")
faw = rd("corpus/fail_after_write.csv")
sig = {r["slot"]: r for r in rd("signals/signals_by_episode.csv")}
cfm = rd("counterfactual/counterfactual_matches_main.csv")
cfs = rd("counterfactual/false_suppressions_main.csv")
ctl = json.load(open(D / "counterfactual/controls_capture_summary.json"))
pilot = rd("pilot/pilot_table_rows.csv")
pilot_cf = rd("pilot/counterfactual_matches.csv")
pilot_first = {"P1": {r["slot"]: r for r in rd("pilot/outcome_labels.csv")},
               "P2": {r["slot"]: r for r in rd("pilot/outcome_labels_E.csv")}}
pilot_second = [{k.split("(")[0]: v for k, v in r.items()} for r in rd("pilot/relabel_pilot_form_completed.csv")]

slots = sorted(master, key=int)
model = {s: sample[master[s]["episode_id"]]["model_id"] for s in slots}
grp = {s: master[s]["group"] for s in slots}
conf = [s for s in slots if master[s]["partial"] == "confirmed"]
det = lambda ss: [s for s in ss if final[s]["harmful_action"] in ("yes", "no")]
harm = lambda ss: [s for s in ss if final[s]["harmful_action"] == "yes"]

# --------------------------------------------------------------------------- corpus (Intro, II)
DUP = set(open(D / "corpus/duplicate_leaderboard_experiments.txt").read().split())
runs = [r for r in runs if not (r["source"] == "leaderboard" and r["experiment"] in DUP)]
put("corpus.runs", len(runs))
put("corpus.runs_usable", sum(r["usable"] == "1" for r in runs))
put("corpus.fail_after_write", len(faw))
put("corpus.rewrite_reissue_pct", round(100 * sum(r["primary_class"] == "modified_rerun_overlap" for r in faw) / len(faw), 1))
put("registry.n", len(registry))
for g in ("legacy", "modern"):
    rr = [r for r in registry if r["group"] == g]
    put(f"registry.{g}.n", len(rr))
    # "configuration" = experiment as in episode_registry.py (agent x model x test split)
    put(f"registry.{g}.configs", len({r["experiment"] for r in rr}))
    put(f"registry.{g}.agent_model_pairs", len({r["experiment"].rsplit("_test_", 1)[0].rsplit("/test_", 1)[0] for r in rr}))
put("registry.extra_vs_static", len(registry) - len(faw))
put("sample.n", len(slots))
put("sample.models", len(set(model.values())))
put("sample.reproduced", sum(1 for s in slots))  # all 200 replayed (REPORT_damage, 211/211)

# --------------------------------------------------------------------------- III
put("confirmed", len(conf))
put("not_confirmed.no_state_change", sum(pc[s]["status"] == "not_confirmed" and "the state did not change" in pc[s]["reason"] for s in slots))
put("not_confirmed.not_in_log", sum(pc[s]["status"] == "not_confirmed" and "not found" in pc[s]["reason"] for s in slots))
put("not_confirmed", sum(pc[s]["status"] == "not_confirmed" for s in slots))
put("undeterminable_partial", sum(pc[s]["status"] == "undeterminable_partial" for s in slots))
put("confirmed.determinable", len(det(conf)))
put("confirmed.harmful", len(harm(det(conf))))
kinds = collections.Counter(final[s]["harm_kind"] for s in harm(conf))
for k in ("duplication", "destruction", "wrong_change", "self_undo"):
    put(f"confirmed.kind.{k}", kinds[k])
for g in ("legacy", "modern"):
    dd = det([s for s in conf if grp[s] == g])
    put(f"stratum.{g}.harmful", len(harm(dd)))
    put(f"stratum.{g}.determinable", len(dd))
    put(f"stratum.{g}.pct", round(100 * len(harm(dd)) / len(dd), 1))
# the authors' scripts/estimate/pooled_estimate.py, run unchanged on the sample with final labels
import decimal, re, subprocess  # noqa: E402
BUILD = ROOT / "build"; BUILD.mkdir(exist_ok=True)
with open(BUILD / "estimate_input.csv", "w", newline="", encoding="utf-8") as fh:
    cols = list(next(iter(master.values())))
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
    for s in slots:
        w.writerow({**master[s], "harmful_action": final[s]["harmful_action"]})
out = subprocess.run([sys.executable, str(ROOT / "scripts/estimate/pooled_estimate.py"), str(BUILD / "estimate_input.csv")],
                     capture_output=True, text=True, check=True).stdout
pct = lambda x: float(decimal.Decimal(x).scaleb(2).quantize(decimal.Decimal("0.1"), decimal.ROUND_HALF_UP))
put("registry_estimate.pct", pct(re.search(r"point (\S+)", out).group(1)))
lo, hi = re.search(r"CI \[(\S+), (\S+)\]", out).groups()
put("registry_estimate.ci", [pct(lo), pct(hi)])
no_oss = det([s for s in conf if model[s] != "gpt-oss-20b"])
put("without_gptoss.harmful", len(harm(no_oss)))
put("without_gptoss.determinable", len(no_oss))
other_modern = det([s for s in conf if grp[s] == "modern" and model[s] != "gpt-oss-20b"])
put("modern_other.determinable", len(other_modern))
put("modern_other.harmful", len(harm(other_modern)))
put("gptoss.sample_modern", sum(model[s] == "gpt-oss-20b" for s in slots if grp[s] == "modern"))
put("gptoss.confirmed_determinable", sum(model[s] == "gpt-oss-20b" for s in det(conf)))
put("harmful_all", len(harm(slots)))
put("harmful_all.residual_yes", sum(final[s]["residual_violation"] == "yes" for s in harm(slots)))
put("harmful_confirmed.residual_yes", sum(final[s]["residual_violation"] == "yes" for s in harm(conf)))
put("harmful_all.residual_undecidable", sorted((s for s in harm(slots) if final[s]["residual_violation"] == "undecidable"), key=int))
nc = det([s for s in slots if master[s]["partial"] == "not_confirmed"])
put("not_confirmed.determinable", len(nc))
put("not_confirmed.harmful", len(harm(nc)))
NONSHOP = ("file_system.", "gmail.", "venmo.", "splitwise.", "phone.", "simple_note.", "spotify.", "todoist.")
put("not_confirmed.harmful.nonshop_write", sum(1 for s in harm(nc) if pc[s]["confirmed_apis"].split(";")[0].startswith(NONSHOP)))
put("confirmed.shopping", sum(1 for s in conf if pc[s]["matched_api"].startswith("amazon.")))
old3 = [s for s in harm(conf) if model[s] in ("gpt-4-turbo-2024-04-09", "gpt-4o-2024-05-13", "meta-llama/Llama-3-70b-chat-hf")]
put("old3.harmful", len(old3))
put("old3.duplication", sum(final[s]["harm_kind"] == "duplication" for s in old3))
oss = [s for s in harm(conf) if model[s] == "gpt-oss-20b"]
put("gptoss.harmful", len(oss))
put("gptoss.not_duplication", sum(final[s]["harm_kind"] != "duplication" for s in oss))
put("gptoss.destruction", sum(final[s]["harm_kind"] == "destruction" for s in oss))
put("gptoss.wrong_change", sum(final[s]["harm_kind"] == "wrong_change" for s in oss))
put("models_2026.sample", sum(model[s] in ("gpt-5.6-luna", "claude-opus-4-7") for s in slots))
put("harmful_confirmed.runs", len({master[s]["source_run"] for s in harm(conf)}))
put("harmful_confirmed.tasks", len({master[s]["task_id"] for s in harm(conf)}))

# Table I
SHORT = {"gpt-4-turbo-2024-04-09": "gpt-4-turbo", "gpt-4o-2024-05-13": "gpt-4o",
         "meta-llama/Llama-3-70b-chat-hf": "llama3-70b", "deepseek-coder-33b-instruct": "deepseekcoder-33b",
         "gpt-oss-20b": "gpt-oss-20b"}
t1 = collections.OrderedDict()
for m in list(SHORT.values()) + ["other models"]:
    t1[m] = [0, 0, 0, 0, 0]
for s in det(conf):
    row = t1[SHORT.get(model[s], "other models")]
    row[0] += 1
    if final[s]["harmful_action"] == "yes":
        row[1] += 1
        row[2 + ("duplication", "destruction", "wrong_change").index(final[s]["harm_kind"])] += 1
t1["Sample"] = [sum(v[i] for v in t1.values()) for i in range(5)]
put("table1", {k: v for k, v in t1.items()})

# Labels
agree = sum(first[s]["harmful_action"] == second[s]["harmful_action"] for s in slots)
put("labels.agreement", agree)
cats = ("yes", "no", "undecidable")
po = agree / len(slots)
pe = sum((sum(first[s]["harmful_action"] == c for s in slots) / len(slots)) *
         (sum(second[s]["harmful_action"] == c for s in slots) / len(slots)) for c in cats)
put("labels.kappa", round((po - pe) / (1 - pe), 2))
put("labels.adjudicated", sum(final[s]["source"].startswith("adjudicated") for s in slots))
# the blind sample of scripts/labels/build_human_tool.py (same rule and seed) is the one labelled by the author
import random  # noqa: E402
_pool = sorted((s for s in final if final[s]["source"].startswith("both agree")), key=int)
put("labels.author_blind_sample_reproduced",
    random.Random(20261115).sample(_pool, 60) == [r["slot"] for r in rd("labels/human/human_blind_labels.csv")])
# author's blind audit of a random sample (harmful_action, three classes) and review of harmful continuations
hb = rd("labels/human/human_blind_labels.csv")
a_, b_ = [r["harmful_action"] for r in hb], [final[r["slot"]]["harmful_action"] for r in hb]
po_ = sum(x == y for x, y in zip(a_, b_)) / len(hb)
pe_ = sum((a_.count(c) / len(hb)) * (b_.count(c) / len(hb)) for c in set(a_) | set(b_))
put("labels.author_blind", [sum(x == y for x, y in zip(a_, b_)), len(hb), round((po_ - pe_) / (1 - pe_), 2)])
hv = rd("labels/human/human_verification.csv")
put("labels.author_review", {"agree": sum(r["author_verdict"] == "agree" for r in hv),
                             "unsure": sorted((r["slot"] for r in hv if r["author_verdict"] == "unsure"), key=int)})
# accounting of the 200 episodes: partial-execution status x final harmful_action (yes / no / undecidable)
put("accounting.by_status", {st: [sum(pc[s]["status"] == st for s in slots)] +
                             [sum(pc[s]["status"] == st and final[s]["harmful_action"] == h for s in slots)
                              for h in ("yes", "no", "undecidable")]
                             for st in ("confirmed", "not_confirmed", "undeterminable_partial")})
put("undeterminable_partial.failed_snapshot", sum(pc[s]["status"] == "undeterminable_partial"
                                                  and pc[s]["reason"].startswith("failed snapshot") for s in slots))
shop = [s for s in det(conf) if pc[s]["confirmed_apis"].split(";")[0].startswith("amazon.")]
other_apps = [s for s in det(conf) if s not in shop]
put("confirmed.shopping.determinable", {"shopping": [len(harm(shop)), len(shop)], "other": [len(harm(other_apps)), len(other_apps)]})
# continuations of determinable confirmed episodes with at least one write call after B
# (labels/first_digests/blind_labels_random_input.csv, n_writes_after_B; failed calls included); bundle only
BLI = D / "protected/labels/first_digests/blind_labels_random_input.csv"
if BLI.is_file():
    csv.field_size_limit(10 ** 9)
    nw = {r["slot"]: int(r["n_writes_after_B"] or 0) for r in rd("protected/labels/first_digests/blind_labels_random_input.csv")}
    with_w = [s for s in det(conf) if nw[s] > 0]
    put("confirmed.determinable.continuation_write", {"with_write": len(with_w), "of": len(det(conf)),
                                                      "harmful_among": len(harm(with_w)), "harmful": len(harm(det(conf)))})
put("labels.first_empty_diff_now_harmful", sum(1 for s in slots if first[s]["harmful_action"] == "no"
                                                and first[s]["change"] == "none" and final[s]["harmful_action"] == "yes"))

# --------------------------------------------------------------------------- IV, Table II
def quality(pred, kind=None, sel=lambda s: True):
    tp = fp = fn = 0
    for s in slots:
        if final[s]["harmful_action"] not in ("yes", "no") or not sel(s):
            continue
        h = final[s]["harmful_action"] == "yes" and (kind is None or final[s]["harm_kind"] == kind)
        x = sig[s][pred] == "1"
        tp += x and h; fp += x and not h; fn += (not x) and h
    return dict(tp=tp, fp=fp, fn=fn, precision=pr(tp, tp + fp), recall=pr(tp, tp + fn))


t2 = {}
for pred, nm in (("rule_b", "Rule B"), ("multiplicity", "Multiplicity test")):
    for kind, kn in ((None, "all harm"), ("duplication", "duplication")):
        q = quality(pred, kind)
        t2[f"{nm} | {kn}"] = [q["precision"], q["recall"]]
put("table2", t2)
put("table2.denominator", {"n": sum(final[s]["harmful_action"] in ("yes", "no") for s in slots),
                          "yes": sum(final[s]["harmful_action"] == "yes" for s in slots),
                          "no": sum(final[s]["harmful_action"] == "no" for s in slots)})
put("rule_b.recall_modern", quality("rule_b", None, lambda s: grp[s] == "modern")["recall"])
put("rule_b.recall_legacy", quality("rule_b", None, lambda s: grp[s] == "legacy")["recall"])
qa = quality("rule_b"); qd = quality("rule_b", "duplication")
put("rule_b.misses", qa["fn"])
put("rule_b.misses.not_duplication", qa["fn"] - qd["fn"])
put("rule_b.misses.duplication", qd["fn"])
ha = harm(slots)
put("harmful_all.duplication_pct", round(100 * sum(final[s]["harm_kind"] == "duplication" for s in ha) / len(ha)))
hm = [s for s in ha if grp[s] == "modern"]
put("harmful_modern.duplication_pct", round(100 * sum(final[s]["harm_kind"] == "duplication" for s in hm) / len(hm)))

# --------------------------------------------------------------------------- V-A, Table III
t3 = {}
for c in "ABCDE":
    g = [r for r in pilot if r["condition"] == c]
    I = lambda k: sum(int(r[k] or 0) for r in g)
    t3[c] = dict(n=len(g), harm=sum(r["harm"] == "yes" for r in g), resid=sum(r["residual"] == "yes" for r in g),
                 harm_undeterminable=sum(r["harm"] == "undecidable" for r in g),
                 byp_req=None if c == "A" else f"{I('bypass')}/{I('n_writes')}",
                 byp_writes=None if c == "A" else f"{I('bypass_ok')}/{I('n_writes_ok')}",
                 rejected=I("rejected"), rejected_followed=I("rej_followed"))
put("table3", t3)
put("pilot.n", [t3[c]["n"] for c in "ABCDE"])
put("pilot.harm", [t3[c]["harm"] for c in "ABCDE"])
put("pilot.resid", [t3[c]["resid"] for c in "ABCDE"])
put("pilot.harm_undeterminable", [t3[c]["harm_undeterminable"] for c in "ABCDE"])
put("pilot.byp_req", [t3[c]["byp_req"] for c in "BCDE"])
put("pilot.byp_writes", [t3[c]["byp_writes"] for c in "BCDE"])
put("pilot.E.rejections_followed", [t3["E"]["rejected_followed"], t3["E"]["rejected"]])
ag = tot = 0
for r in pilot_second:
    src, _, s = r["item"].partition("-")
    L = pilot_first[src].get(s)
    if L:
        tot += 1; ag += L["harmful_action"] == r["harmful_action"]
put("pilot.relabel_agreement", [ag, tot])
put("pilot.cf_matched", [sum(int(r[f"match_{f}"]) for r in pilot_cf) for f in ("strict", "lenient", "ids")] + [len(pilot_cf)])

# --------------------------------------------------------------------------- V-B, Table IV
confk = {key_of(master[s]["episode_id"]) for s in conf}
harm_confk = {key_of(master[s]["episode_id"]) for s in harm(conf)}
kind_of = {key_of(master[s]["episode_id"]): final[s]["harm_kind"] for s in harm(conf)}
model_of = {key_of(master[s]["episode_id"]): model[s] for s in slots}
F = ("strict", "lenient", "ids")
W = [r for r in cfm if r["key"] in harm_confk]
by = collections.defaultdict(list)
for r in W:
    by[r["key"]].append(r)
t4 = collections.OrderedDict()
t4["Harmful writes matched"] = [len(W)] + [sum(int(r[f"match_{f}"]) for r in W) for f in F]
for k, nm in (("duplication", "duplication"), ("destruction", "destruction"), ("wrong_change", "wrong change")):
    g = [r for r in W if r["type"] == k]
    t4[f"  {nm} (writes)"] = [len(g)] + [sum(int(r[f"match_{f}"]) for r in g) for f in F]
full = {f: {k for k, rr in by.items() if all(r[f"match_{f}"] == "1" for r in rr)} for f in F}
t4["Recoveries fully matched"] = [len(harm_confk)] + [len(full[f]) for f in F]
for k, nm in (("duplication", "duplication"), ("destruction", "destruction"), ("wrong_change", "wrong change")):
    ks = [x for x in harm_confk if kind_of[x] == k]
    t4[f"  {nm} (recoveries)"] = [len(ks)] + [sum(x in full[f] for x in ks) for f in F]
FS = [r for r in cfs if r["key"] in confk]
need = {f: [r for r in FS if r[f"match_{f}"] == "1" and r["needed_by_task"] == "yes"] for f in F}
t4["Required writes matched"] = [None] + [len(need[f]) for f in F]
t4["  episodes with such writes"] = [None] + [len({r["key"] for r in need[f]}) for f in F]
put("table4", t4)
put("cf.harmful_writes_ambiguous", sum(r["ambiguous"] == "1" for r in W))
nonamb = [r for r in W if r["ambiguous"] != "1"]
put("cf.non_ambiguous", [sum(int(r[f"match_{f}"]) for r in nonamb) for f in F] + [len(nonamb)])
put("cf.early_matches", [sum(1 for r in W if r[f"match_{f}"] == "1" and r[f"matched_{f}"].startswith("early")) for f in F])
dup = [r for r in W if r["type"] == "duplication"]
put("cf.duplication_strict_pct", round(100 * sum(int(r["match_strict"]) for r in dup) / len(dup)))
put("cf.ids_only_address_writes", sum(1 for r in W if r["api"] == "amazon.add_address" and r["match_ids"] == "1" and r["match_strict"] == "0"))
put("cf.destruction_lenient_only", sum(1 for r in W if r["type"] == "destruction" and r["match_lenient"] == "1" and r["match_strict"] == "0"))
old3k = {x for x in harm_confk if model_of[x] in ("gpt-4-turbo-2024-04-09", "gpt-4o-2024-05-13", "meta-llama/Llama-3-70b-chat-hf")}
put("cf.full.old3", [sum(x in full[f] for x in old3k) for f in F] + [len(old3k)])
ossk = {x for x in harm_confk if model_of[x] == "gpt-oss-20b"}
put("cf.full.gptoss", [sum(x in full[f] for x in ossk) for f in F] + [len(ossk)])
put("cf.nonharmful_matched_confirmed", [sum(1 for r in FS if r[f"match_{f}"] == "1") for f in F])
apis = set()
for f in F:
    apis |= {r["api"] for r in need[f]}
put("cf.required_apis", sorted(apis))
put("cf.required_episodes_without_harm", len({r["key"] for r in need["strict"]} - harm_confk))
put("cf.controls_pass", sum(1 for v in ctl.values() if v == 0))
put("cf.controls_pass_harmful_confirmed", sum(1 for x in harm_confk if ctl.get(x) == 0))


# --------------------------------------------------------------------------- print
def show():
    print("TABLE I  Residual harm after confirmed partial execution by model (determinable)")
    print(f"{'Model':20s} {'Conf.':>5s} {'Harm':>5s} {'Dupl.':>5s} {'Destr.':>6s} {'Wrong':>5s}")
    for k, v in t1.items():
        print(f"{k:20s} " + " ".join(f"{x:>5d}" for x in v))
    print("\nTABLE II  Automatic signals against state-and-task labels (195 sampled episodes with a determinable label)")
    for k, (p, r) in t2.items():
        print(f"{k:34s} precision {p:.2f}  recall {r:.2f}")
    print("\nTABLE III  Pilot with model-supplied identifiers")
    print(f"{'':2s} {'n':>3s} {'Harm':>5s} {'Resid.':>6s} {'Byp. req.':>10s} {'Byp. writes':>12s}")
    for c, v in t3.items():
        print(f"{c:2s} {v['n']:>3d} {v['harm']:>5d} {v['resid']:>6d} {v['byp_req'] or '-':>10s} {v['byp_writes'] or '-':>12s}")
    print("\nTABLE IV  Counterfactual matching on canonical arguments, 30 harmful recoveries")
    print(f"{'':32s} {'Total':>6s} {'Strict':>7s} {'Lenient':>8s} {'Ids':>5s}")
    for k, v in t4.items():
        print(f"{k:32s} " + " ".join(f"{('-' if x is None else x):>{w}}" for x, w in zip(v, (6, 7, 8, 5))))
    print("\nTEXT NUMBERS")
    for k, v in OUT.items():
        if not k.startswith("table"):
            print(f"  {k:45s} {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    show()
    if a.json:
        json.dump(OUT, open(a.json, "w"), ensure_ascii=False, indent=1, default=str)
