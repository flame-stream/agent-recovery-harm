#!/usr/bin/env python3
"""Plain-text rendering of a blind digest for the labeller (same content, less markup).
net A->C is shown only where it differs from net B->C (that is the block's own effect)."""
import json, sys

def rows(d, ind="    "):
    out = []
    for t, v in d.items():
        if isinstance(v, str):
            out.append(f"{ind}{t}: {v}"); continue
        out.append(f"{ind}{t}: +{v['n_added']} / -{v['n_removed']}")
        out += [f"{ind}  + {x}" for x in v["added"]]
        out += [f"{ind}  - {x}" for x in v["removed"]]
    return out

for it in json.load(open(sys.argv[1])):
    L = [f"=== slot {it['slot']}", f"TASK: {it['task']}"]
    w = it["continuation_write_calls"]
    L.append(f"WRITE-CONTINUATION CALLS: total {w['n_write_calls']}, with effect {len(w['with_effect']) + w['with_effect_not_shown']}")
    for c in w["with_effect"]:
        L.append(f"  #{c['n']} {c['api']} {json.dumps(c['args'], ensure_ascii=False)[:200]}" + (f"  ERROR {c['error'][:100]}" if c['error'] else ""))
        if isinstance(c["delta"], str):
            L.append(f"      {c['delta']}")
        else:
            for t, x in c["delta"].items():
                L += [f"      {t} + {a}" for a in x["added"]] + [f"      {t} - {a}" for a in x["removed"]]
    if w["with_effect_not_shown"]:
        L.append(f"  … more {w['with_effect_not_shown']} calls with effect not shown")
    for c in w["no_effect"]:
        L.append(f"  without effect: {c['api']} ×{c['times']} → {c['result']}")
    L.append("TOTAL B→C (continuation):"); L += rows(it["net_B_to_C"]) or ["    empty"]
    extra = {t: v for t, v in it["net_A_to_C"].items() if it["net_B_to_C"].get(t) != v}
    if extra:
        L.append("TOTAL A→C where it differs (includes the effect of the block under study):"); L += rows(extra)
    if it["user_rows_in_A"]:
        L.append("USER ROWS IN A (latest):")
        for t, v in it["user_rows_in_A"].items():
            L.append(f"    {t}: total {v['n_user_rows_in_A']}, of them created in the episode before A: {v.get('n_created_in_episode_before_A')}")
            made = v.get("created_in_episode_before_A") or []
            L += [f"      [created in the episode] {x}" for x in made[-6:]]
            if not made:
                L += [f"      {x}" for x in v["last_rows"][-4:]]
    print("\n".join(L) + "\n")
