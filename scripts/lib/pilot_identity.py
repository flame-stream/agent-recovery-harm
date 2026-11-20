#!/usr/bin/env python3
"""Section 7 diagnostics: identity errors, read from the operation journals.

Correctness of identity is judged against the task and the history, not against the
journal itself; the journal only supplies what the model actually did.
  split   — one logical operation carried more than one id
  merge   — different logical operations shared one id
  changed_args_same_id — a completed id reused with different arguments
  returned_ok — a stored result returned where the operation really was the same
  bypass  — a write that did not go through the wrapper
"""
import collections, csv, json, pathlib


def logical_key(e):
    """The logical operation a call belongs to: api plus its entity arguments."""
    args = {k: v for k, v in (e.get("args") or {}).items()
            if k not in ("access_token", "password", "file_system_access_token")}
    return (e["api"], json.dumps(args, sort_keys=True, default=str))


def main():
    eps = {r["episode_id"]: r for r in csv.DictReader(open("episodes.csv"))}
    rows = []
    for p in sorted(pathlib.Path("pilot_out").glob("journal_*.json")):
        j = json.load(open(p))
        stem = p.stem[len("journal_"):]
        cond, task, block = stem.split("__")
        if not j:
            rows.append(dict(condition=cond, task_id=task, block=block, n_ops=0,
                             split=0, merge=0, changed_args_same_id=0,
                             returned_ok=0, returned_wrong=0, conflicts=0,
                             note="log empty"))
            continue
        by_id = collections.defaultdict(list)
        by_key = collections.defaultdict(set)
        for e in j:
            by_id[e["op"]].append(e)
            by_key[logical_key(e)].add(e["op"])
        split = sum(1 for k, v in by_key.items() if len(v) > 1)
        merge = sum(1 for oid, v in by_id.items()
                    if len({logical_key(e) for e in v}) > 1)
        changed = sum(1 for e in j if e["decision"] == "operation_conflict")
        ret = [e for e in j if e["decision"] == "returned_stored"]
        ret_ok = 0
        for e in ret:
            first = next((x for x in by_id[e["op"]] if x["decision"] == "executed"), None)
            if first and logical_key(first) == logical_key(e):
                ret_ok += 1
        rows.append(dict(condition=cond, task_id=task, block=block, n_ops=len(by_id),
                         split=split, merge=merge, changed_args_same_id=changed,
                         returned_ok=ret_ok, returned_wrong=len(ret) - ret_ok,
                         conflicts=changed, note=""))
    if not rows:
        print("no logs"); return
    with open("identity_labels.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print("| condition | episodes | operations | split | merge | conflicts | correct return | wrong return |")
    print("|---|--:|--:|--:|--:|--:|--:|--:|")
    for c in ("B", "C", "D"):
        g = [r for r in rows if r["condition"] == c]
        if not g:
            continue
        print(f"| {c} | {len(g)} | {sum(r['n_ops'] for r in g)} | {sum(r['split'] for r in g)} "
              f"| {sum(r['merge'] for r in g)} | {sum(r['conflicts'] for r in g)} "
              f"| {sum(r['returned_ok'] for r in g)} | {sum(r['returned_wrong'] for r in g)} |")


if __name__ == "__main__":
    main()
