#!/usr/bin/env python3
"""Step 6 input: blind table for the random samples.

Hidden: group, configuration, model. Shown: task text, what the failed block made
(A->B), every write call between B and C with its own diff, and the net B->C change.
Shuffled with a fixed seed. The mechanical flags of step 5 are NOT shown.
"""
import collections, csv, json, pathlib, random, sys

SHUFFLE_SEED = 4242
csv.field_size_limit(10**9)
SPEC = {}


def instruction(task_id):
    if task_id not in SPEC:
        p = pathlib.Path("data/tasks") / task_id / "specs.json"
        try:
            SPEC[task_id] = json.load(open(p)).get("instruction", "")
        except Exception:
            SPEC[task_id] = ""
    return SPEC[task_id]


def compact(rows, limit=6):
    out = []
    for r in rows[:limit]:
        try:
            d = json.loads(r)
        except Exception:
            out.append(r[:120]); continue
        keep = {k: v for k, v in d.items()
                if k in ("id", "product_id", "quantity", "gift_wrap_quantity", "user_id",
                         "name", "path", "amount", "email_id", "email_thread_id",
                         "street_address", "order_id", "balance", "status")}
        out.append(json.dumps(keep or d, ensure_ascii=False)[:160])
    if len(rows) > limit:
        out.append(f"...more {len(rows)-limit}")
    return out


def diff_tables(x, y):
    res = {}
    for t in set(list(x) + list(y)):
        a, b = collections.Counter(x.get(t, [])), collections.Counter(y.get(t, []))
        add, rem = list((b - a).elements()), list((a - b).elements())
        if add or rem:
            res[t] = dict(added=compact(add), removed=compact(rem),
                          n_added=len(add), n_removed=len(rem))
    return res


def main():
    reg = {r["episode_id"]: r for r in csv.DictReader(open("episode_registry.csv"))}
    status = {}
    for f in pathlib.Path(".").glob("replay_status_*.json"):
        for r in json.load(open(f)):
            status[r["episode_id"]] = r
    want = set()
    for g in ("legacy", "modern"):
        want |= {r["episode_id"] for r in csv.DictReader(open(f"random_sample_{g}.csv"))}
    rows = []
    for eid in sorted(want):
        ep = reg[eid]
        st = status.get(eid, {})
        key = eid.replace("/", "~").replace("|", "__")
        sp = pathlib.Path("damage_out/snapshots") / f"{key}.json"
        cp = pathlib.Path("damage_out/call_diffs") / f"{key}.json"
        if not (st.get("ok") and sp.exists()):
            rows.append(dict(episode_id=eid, task_id=ep["task_id"],
                             instruction=instruction(ep["task_id"]),
                             reproduced=0,
                             reason=st.get("reason", "not run"),
                             made_by_failed_block="", writes_after_B="",
                             net_B_to_C="", n_writes_after_B=0))
            continue
        s = json.load(open(sp))
        calls = json.load(open(cp)) if cp.exists() else []
        made = diff_tables(s["A"], s["B"])
        net = diff_tables(s["B"], s["C"])
        wr = []
        for c in calls:
            d = {t: dict(n_added=v["n_added"], n_removed=v["n_removed"],
                         added=compact(v["added"], 3), removed=compact(v["removed"], 3))
                 for t, v in (c["delta"] or {}).items()}
            wr.append(dict(api=c["api"], args={k: v for k, v in c["args"].items()
                                               if k != "access_token"},
                           error=c["error"], delta=d))
        rows.append(dict(episode_id=eid, task_id=ep["task_id"],
                         instruction=instruction(ep["task_id"]), reproduced=1, reason="",
                         made_by_failed_block=json.dumps(made, ensure_ascii=False),
                         writes_after_B=json.dumps(wr, ensure_ascii=False),
                         net_B_to_C=json.dumps(net, ensure_ascii=False),
                         n_writes_after_B=len(wr)))
    rnd = random.Random(SHUFFLE_SEED)
    rnd.shuffle(rows)
    for i, r in enumerate(rows, 1):
        r["slot"] = i
    with open("blind_labels_random_input.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["slot"] + [k for k in rows[0] if k != "slot"])
        w.writeheader(); w.writerows(rows)
    with open("blind_labels_random_map.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["slot", "episode_id", "group", "experiment", "model_id"])
        for r in rows:
            e = reg[r["episode_id"]]
            w.writerow([r["slot"], r["episode_id"], e["group"], e["experiment"], e["model_id"]])
    print(f"blind table: {len(rows)} episodes (seed={SHUFFLE_SEED}); "
          f"reproduced {sum(r['reproduced'] for r in rows)}")


if __name__ == "__main__":
    main()
