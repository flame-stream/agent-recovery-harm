#!/usr/bin/env python3
"""Step 1: pick at most 20 episodes for the pilot.

10 with a confirmed harmful repeat; up to 10 with legitimate repeats after a partial
execution. Rules fixed before looking: at most 2 episodes per source run, spread over
API families, and the harmful ten keep the harm-kind mix of the pool.
"""
import collections, csv, json, pathlib, random, re

SEED = 7717
csv.field_size_limit(10**9)
ITER = re.compile(r"\b(keep going|until you|one by one|each of|for each|every |all the |"
                  r"respond to all|reply to (all|each))\b", re.I)
SPEC = {}


def instr(t):
    if t not in SPEC:
        p = pathlib.Path("data/tasks") / t / "specs.json"
        SPEC[t] = json.load(open(p)).get("instruction", "") if p.exists() else ""
    return SPEC[t]


def family(api):
    app = (api or "").split(".")[0]
    return {"amazon": "amazon", "gmail": "gmail", "file_system": "filesystem",
            "venmo": "payments", "splitwise": "payments", "spotify": "spotify"}.get(app, "other")


def main():
    master = {r["slot"]: r for r in csv.DictReader(open("damage_master_table.csv"))}
    lab = {r["slot"]: r for r in csv.DictReader(open("history_labels.csv"))}
    reg = {r["episode_id"]: r for r in csv.DictReader(open("episode_registry.csv"))}
    rnd = random.Random(SEED)

    def api_of(eid):
        return (reg[eid]["write_confirmed"] or "").split(";")[0].split("@")[0]

    # --- harmful ten ---
    pool = [r for r in master.values()
            if r["harmful_action"] == "yes" and r["partial"] == "confirmed"]
    for r in pool:
        r["kind"] = lab[r["slot"]]["harm_kind"]
        r["api"] = api_of(r["episode_id"])
        r["family"] = family(r["api"])
    rnd.shuffle(pool)
    chosen, per_run, per_fam = [], collections.Counter(), collections.Counter()
    for want_fam_spread in (True, False):
        for r in pool:
            if len(chosen) >= 10 or r in chosen:
                continue
            if per_run[r["source_run"]] >= 2:
                continue
            if want_fam_spread and per_fam[r["family"]] >= 3:
                continue
            chosen.append(r); per_run[r["source_run"]] += 1; per_fam[r["family"]] += 1

    # --- legitimate repeats ---
    # a legitimate repeat is either a task that literally asks for repetition, or a
    # continuation that calls one write API more than once on DIFFERENT entities
    def repeats_on_different_entities(eid):
        k = eid.replace("/", "~").replace("|", "__")
        p = pathlib.Path("damage_out/call_diffs") / f"{k}.json"
        if not p.exists():
            return False
        seen = collections.defaultdict(set)
        for c in json.load(open(p)):
            if not c["delta"]:
                continue
            a = json.dumps({x: y for x, y in c["args"].items()}, sort_keys=True)
            seen[c["api"]].add(a)
        return any(len(v) >= 2 for v in seen.values())

    legit = []
    for r in master.values():
        if r["harmful_action"] != "no" or r["partial"] != "confirmed":
            continue
        eid = r["episode_id"]
        txt = instr(r["task_id"])
        if not (ITER.search(txt) or repeats_on_different_entities(eid)):
            continue
        r["kind"] = "legit"
        r["api"] = api_of(eid)
        r["family"] = family(r["api"])
        legit.append(r)
    rnd.shuffle(legit)
    picked_l, per_run_l, per_fam_l = [], collections.Counter(), collections.Counter()
    for r in legit:
        if len(picked_l) >= 10:
            break
        if per_run_l[r["source_run"]] >= 2 or per_fam_l[r["family"]] >= 6:
            continue
        if per_run[r["source_run"]] + per_run_l[r["source_run"]] >= 2:
            continue
        picked_l.append(r); per_run_l[r["source_run"]] += 1; per_fam_l[r["family"]] += 1

    rows = []
    for r in chosen:
        rows.append(dict(slot=r["slot"], episode_id=r["episode_id"], arm="harmful",
                         group=r["group"], experiment=r["experiment"],
                         task_id=r["task_id"], source_run=r["source_run"],
                         api=r["api"], family=r["family"], harm_kind=r["kind"],
                         block=reg[r["episode_id"]]["block"],
                         path=reg[r["episode_id"]]["path"],
                         data_version=reg[r["episode_id"]]["data_version"],
                         instruction=instr(r["task_id"])[:300]))
    for r in picked_l:
        rows.append(dict(slot=r["slot"], episode_id=r["episode_id"], arm="legit",
                         group=r["group"], experiment=r["experiment"],
                         task_id=r["task_id"], source_run=r["source_run"],
                         api=r["api"], family=r["family"], harm_kind="",
                         block=reg[r["episode_id"]]["block"],
                         path=reg[r["episode_id"]]["path"],
                         data_version=reg[r["episode_id"]]["data_version"],
                         instruction=instr(r["task_id"])[:300]))
    with open("episodes.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"selected: {len(rows)} (harmful {len(chosen)}, legitimate {len(picked_l)}), seed={SEED}")
    for a in ("harmful", "legit"):
        g = [r for r in rows if r["arm"] == a]
        print(f"  {a}: families {dict(collections.Counter(r['family'] for r in g))}, "
              f"kinds {dict(collections.Counter(r['harm_kind'] for r in g if r['harm_kind']))}, "
              f"runs {len({r['source_run'] for r in g})}, "
              f"data versions {dict(collections.Counter(r['data_version'] for r in g))}")
    mx = collections.Counter(r["source_run"] for r in rows).most_common(1)
    print("maximum episodes from one run:", mx[0][1] if mx else 0)


if __name__ == "__main__":
    main()
