#!/usr/bin/env python3
"""Step 1: rule B, the code from the replay report, unchanged, on both groups.

Rule B is `step5_recount.rule_b`, imported verbatim, NOT `harmful_candidate`
(that is rule A in the same report: 1128 episodes of 1897). Rule B additionally
requires the repeated API to be `duplicating` or `accumulating` by the idempotency
table, and already excludes add_product_to_cart(clear_cart_first=True) as net
idempotent. No B'. The result feeds steps 5 and 8 only, never the labelling.
"""
import collections, csv, pathlib, sys
sys.path.insert(0, ".")
import appworld_audit as A
import appworld_recovery as R
# the one documented detector change: LARA MAS routes calls through call_api(); without
# it 13 modern episodes have no visible confirmed write. Rule B itself is untouched.
import fresh_detect2  # noqa: F401  (installs the wrapper-aware _calls_in)
from step5_recount import rule_b as RULE_B
csv.field_size_limit(10**9)


def main():
    reg = list(csv.DictReader(open("episode_registry.csv")))
    by_run = collections.defaultdict(list)
    for r in reg:
        by_run[(r["path"], r["task_id"])].append(r)
    out = []
    for (path, tid), eps in sorted(by_run.items()):
        td = pathlib.Path(path)
        try:
            blocks = A.parse_blocks(td / "logs" / "environment_io.md")
        except Exception:
            continue
        try:
            recs, _ = A.analyse_run(td)      # the original record shape rule B expects
        except Exception:
            continue
        dup = R.db_duplicate_groups(td)
        pos = {b["index"]: i for i, b in enumerate(blocks)}
        for ep in eps:
            i = pos.get(int(ep["block"]))
            if i is None:
                out.append(dict(ep, rule_a=0, rule_b=0, repeated_api="", note="block not found"))
                continue
            try:
                res = R.analyse_episode(blocks, recs, i, td, dup)
            except Exception as e:
                out.append(dict(ep, rule_a=0, rule_b=0, repeated_api="",
                                note=f"{type(e).__name__}"))
                continue
            if res is None:
                out.append(dict(ep, rule_a=0, rule_b=0, repeated_api="",
                                note="no confirmed write"))
                continue
            row = dict(ep)
            row.update({k: res.get(k, "") for k in
                        ("repeat_confirmed_write", "new_effect", "repeated_api",
                         "repeat_block", "harmful_candidate")})
            # rule B's cart carve-out. analyse_episode returns repeat_block as the
            # block LABEL (recs[j]["block"]), not a list position; step5_recount keys
            # its cart set by that same label, so look the block up by label.
            cc = set()
            rb = res.get("repeat_block")
            by_label = {b["index"]: b for b in blocks}
            probe = dict(row)
            probe["path"] = str(path)
            probe["repeat_block"] = str(rb) if rb not in (None, "") else ""
            if res.get("repeated_api") == "amazon.add_product_to_cart" and rb not in (None, ""):
                b = by_label.get(int(rb))
                if b and "clear_cart_first" in (b["code"] or "") and "True" in b["code"]:
                    cc.add(str(path) + "#" + str(rb))
            out.append(dict(row, rule_a=int(res["harmful_candidate"]),
                            rule_b=RULE_B(probe, cc), note=""))
    cols = sorted({k for r in out for k in r})
    with open("rule_b_candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(out)
    for g in ("legacy", "modern"):
        gg = [r for r in out if r["group"] == g]
        ka = sum(r.get("rule_a", 0) for r in gg); kb = sum(r.get("rule_b", 0) for r in gg)
        print(f"{g}: episodes {len(gg)} | rule A {ka} ({100.0*ka/len(gg):.1f} %) | "
              f"rule B {kb} ({100.0*kb/len(gg):.1f} %) | runs with a candidate B "
              f"{len({r['source_run'] for r in gg if r.get('rule_b')})}")
    print("total for B:", sum(r.get("rule_b", 0) for r in out))


if __name__ == "__main__":
    main()
