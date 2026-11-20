#!/usr/bin/env python3
"""Step 1 input: every state-changing write between B and C, in substance.

Substance = the row minus surrogate id / hash / timestamps, so re-inserting the same
content under a new id is not a change. For each episode we surface the signatures a
task judgement needs:
  - deletions of rows that existed at A (candidate `destruction`)
  - additions whose content already existed at that moment (candidate `duplication`)
  - quantity raised on a cart key
  - anything else that moved (candidate `wrong_change`)
The final B->C diff is reported separately as a flag, with no inference about rollback.
"""
import collections, csv, json, pathlib, sys, textwrap
csv.field_size_limit(10**9)
VOL = ("id", "record_hash", "created_at", "updated_at")
SPEC = {}


def instr(t):
    if t not in SPEC:
        p = pathlib.Path("data/tasks") / t / "specs.json"
        SPEC[t] = json.load(open(p)).get("instruction", "") if p.exists() else ""
    return SPEC[t]


def sub(row):
    # rows in call_diffs are truncated at 600 chars, so long ones are not valid JSON
    try:
        d = json.loads(row)
    except Exception:
        return "TRUNC:" + row[:300]
    return json.dumps({k: v for k, v in d.items() if k not in VOL}, sort_keys=True)


def short(js, n=4):
    try:
        d = json.loads(js)
    except Exception:
        return js[:110]
    return ", ".join(f"{k}={str(v)[:26]}" for k, v in list(d.items())[:n])


def main():
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    mp = {r["slot"]: r for r in csv.DictReader(open("blind_labels_random_map.csv"))}
    inp = {r["slot"]: r for r in csv.DictReader(open("blind_labels_random_input.csv"))}
    for s in map(str, range(lo, hi + 1)):
        if s not in mp:
            continue
        k = mp[s]["episode_id"].replace("/", "~").replace("|", "__")
        cp = pathlib.Path("damage_out/call_diffs") / f"{k}.json"
        sp = pathlib.Path("damage_out/snapshots") / f"{k}.json"
        if not cp.exists():
            continue
        calls = json.load(open(cp))
        snap = json.load(open(sp))
        at_A = {t: collections.Counter(sub(x) for x in v) for t, v in snap["A"].items()}
        # drop calls whose delta is the signature of a failed snapshot in the chain:
        # four or more whole tables vanish or appear at once. 12 of 200 episodes have
        # such calls; for them the call-level evidence is unusable and the episode falls
        # back to the net B->C diff.
        def broken(c):
            d = c["delta"]
            rem = [t for t, v in d.items() if v["n_added"] == 0 and v["n_removed"] > 0]
            add = [t for t, v in d.items() if v["n_removed"] == 0 and v["n_added"] > 0]
            if len(rem) >= 3 or len(add) >= 3:
                return True
            # a single API call never wipes or fills 50+ rows of one table here
            return any((v["n_removed"] >= 50 and v["n_added"] == 0)
                       or (v["n_added"] >= 50 and v["n_removed"] == 0)
                       for v in d.values())
        n_broken = sum(1 for c in calls if c["delta"] and broken(c))
        changing = [c for c in calls if c["delta"] and not broken(c)]
        if not changing:
            continue
        net_empty = all(snap["B"].get(t) == snap["C"].get(t)
                        for t in set(list(snap["B"]) + list(snap["C"])))
        lines = []
        seen = collections.Counter()
        for c in changing:
            for t, d in c["delta"].items():
                add = [sub(x) for x in d["added"]]
                rem = [sub(x) for x in d["removed"]]
                real_add = [x for x in add if x not in rem]
                real_rem = [x for x in rem if x not in add]
                tags = []
                for x in real_rem:
                    if at_A.get(t, {}).get(x):
                        tags.append(f"DELETED what existed before A: {short(x)}")
                for x in real_add:
                    if seen[x]:
                        tags.append(f"REPEATED addition of the same: {short(x)}")
                    seen[x] += 1
                if not tags and (real_add or real_rem):
                    tags.append(f"+{len(real_add)}/-{len(real_rem)} {t.split('.')[-1]}: "
                                + (short(real_add[0]) if real_add else short(real_rem[0])))
                for tg in tags[:3]:
                    lines.append(f"    [{c['api'].split('.')[-1]}] {tg}")
        if not lines:
            continue
        print("=" * 98)
        print(f"SLOT {s} | {inp[s]['task_id']} | changing calls: {len(changing)}"
              + (f" (+{n_broken} with failed snapshot)" if n_broken else "")
              + f" | net B→C {'EMPTY' if net_empty else 'non-empty'}")
        print(textwrap.fill("TASK: " + instr(inp[s]["task_id"]), 96, subsequent_indent="   "))
        for l in lines[:10]:
            print(l)
        if len(lines) > 10:
            print(f"    ...more {len(lines)-10} lines")


if __name__ == "__main__":
    main()
