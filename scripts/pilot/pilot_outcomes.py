#!/usr/bin/env python3
"""Section 7/8: outcome measures per continuation, from the frozen instrument.

Harm and residual violation are judged blind: the digest below hides the condition.
False suppression is counted from the journal — a stored result returned for what is
actually a different operation, or an operation_conflict raised against a legitimate
new operation. Both are suppressions the mechanism performed because of an identity
error; the cause is recorded separately from the count.
"""
import collections, csv, glob, json, pathlib, random, sys
sys.path.insert(0, ".")
import instrument as I
from pilot_identity import logical_key

SHUFFLE_SEED = 5150


def net_subject(snap):
    B, C = snap["B"], snap["C"]
    out = {}
    for t in sorted(set(list(B) + list(C))):
        cb = collections.Counter(I.substance(x) for x in B.get(t, []))
        cc = collections.Counter(I.substance(x) for x in C.get(t, []))
        add, rem = list((cc - cb).elements()), list((cb - cc).elements())
        if add or rem:
            out[t] = dict(added=add[:6], removed=rem[:6], n_added=len(add),
                          n_removed=len(rem))
    return out


def main():
    eps = {r["episode_id"]: r for r in csv.DictReader(open("episodes.csv"))}
    by_task = {(r["task_id"], r["block"]): r for r in eps.values()}
    rows = []
    for f in sorted(glob.glob("pilot_results_*.json")):
        for r in json.load(open(f)):
            if not r.get("usable"):
                continue
            key = f"{r['condition']}__{r['task_id']}__{r['block']}"
            sp = pathlib.Path("pilot_out") / f"snap_{key}.json"
            jp = pathlib.Path("pilot_out") / f"journal_{key}.json"
            if not sp.exists():
                continue
            snap = json.load(open(sp))
            j = json.load(open(jp)) if jp.exists() else []
            ep = by_task.get((r["task_id"], r["block"]), {})
            # false suppression, from the journal
            by_id = collections.defaultdict(list)
            for e in j:
                by_id[e["op"]].append(e)
            fs_return = fs_conflict = 0
            for e in j:
                if e["decision"] == "returned_stored":
                    first = next((x for x in by_id[e["op"]] if x["decision"] == "executed"), None)
                    if first and logical_key(first) != logical_key(e):
                        fs_return += 1
                if e["decision"] == "operation_conflict":
                    fs_conflict += 1
            rows.append(dict(key=key, condition=r["condition"], arm=ep.get("arm", ""),
                             task_id=r["task_id"], block=r["block"],
                             outcome=r.get("outcome"), evaluator=r.get("evaluator"),
                             flag=r.get("flag"), n_steps=r.get("n_steps"),
                             tokens=r.get("tokens"), seconds=r.get("seconds"),
                             n_journal=len(j), n_bypass=r.get("n_bypass", 0),
                             fs_return=fs_return, fs_conflict=fs_conflict,
                             subject=json.dumps(net_subject(snap), ensure_ascii=False)[:1500]))
    if not rows:
        print("no results"); return
    with open("outcome_raw.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    # blind digest for harm labelling
    rnd = random.Random(SHUFFLE_SEED)
    blind = [dict(slot=i + 1, task_id=r["task_id"], block=r["block"], arm=r["arm"],
                  subject=r["subject"], key=r["key"])
             for i, r in enumerate(sorted(rows, key=lambda x: rnd.random()))]
    json.dump(blind, open("outcome_blind.json", "w"), ensure_ascii=False, indent=1)
    print(f"continuations with a measurement: {len(rows)}")
    for c in ("A", "B", "C", "D"):
        g = [r for r in rows if r["condition"] == c]
        if not g:
            continue
        print(f"  {c}: n={len(g)} | flags={dict(collections.Counter(r['flag'] for r in g))} "
              f"| outcomes={dict(collections.Counter(r['outcome'] for r in g))} "
              f"| suppressions: return {sum(r['fs_return'] for r in g)}, "
              f"conflict {sum(r['fs_conflict'] for r in g)} | bypass {sum(r['n_bypass'] for r in g)}")


if __name__ == "__main__":
    main()
