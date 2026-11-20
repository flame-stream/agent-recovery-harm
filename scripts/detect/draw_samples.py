#!/usr/bin/env python3
"""Step 2: simple random samples of 100 per group. Seed fixed before any inspection."""
import collections, csv, random

SAMPLE_SEED = 20250920      # fixed here, before the samples were looked at
N = 100
reg = list(csv.DictReader(open("episode_registry.csv")))
for g in ("legacy", "modern"):
    pool = sorted([r for r in reg if r["group"] == g], key=lambda r: r["episode_id"])
    s = random.Random(SAMPLE_SEED).sample(pool, min(N, len(pool)))
    with open(f"random_sample_{g}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(s[0])); w.writeheader(); w.writerows(s)
    print(f"\n## {g}: {len(s)} of {len(pool)} (seed={SAMPLE_SEED})")
    for key, lab in (("experiment", "configuration"), ("model_id", "model"),
                     ("data_version", "data version")):
        c = collections.Counter(r[key] for r in s)
        print(f"  {lab}: " + ", ".join(f"{k} {v}" for k, v in c.most_common(6)))
    api = collections.Counter((r["write_confirmed"].split(";")[0] or "").split("@")[0]
                              for r in s)
    print("  API of the confirmed write: " + ", ".join(f"{k} {v}" for k, v in api.most_common(6)))
    print(f"  unique runs: {len({r['source_run'] for r in s})}")
