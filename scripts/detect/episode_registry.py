#!/usr/bin/env python3
"""Step 0: one registry of every fail_after_write episode, with non-overlapping groups.

GROUPS ARE FIXED BY MODEL ID, BEFORE ANY SAMPLING
  legacy : models released in 2024 or earlier
           GPT-4o (05-13 and 08-06), GPT-4 Turbo, DeepSeekCoder-33B, LLaMA3-70B, Qwen2.5-32B
  modern : 2025+ model families
           GPT-4.1, gpt-4.1-mini, Claude Opus 4.6, claude-opus-4-7, Claude Sonnet 4.6,
           gpt-5.6-luna, Qwen3-14B, gpt-oss-20b
No run belongs to both: the 28 leaderboard copies that are byte-identical to the
`official` experiment-outputs were dropped in fresh_runs_inventory.csv and stay dropped.
"""
import csv, collections, pathlib, sys
csv.field_size_limit(10**9)

LEGACY_MODELS = {"GPT-4o", "GPT-4 Turbo", "DeepSeekCoder", "LLaMA3-70B",
                 "GPT-4o (2024-05-13)", "GPT-4 Turbo (2024-04-09)", "DeepSeekCoder-33B",
                 "Qwen2.5-32B"}
MODERN_MODELS = {"GPT-4.1", "gpt-4.1-mini", "Claude Opus 4.6", "claude-opus-4-7",
                 "Claude Sonnet 4.6", "gpt-5.6-luna", "Qwen3-14B", "gptoss-20b"}
MODEL_ID = {
    "GPT-4o": "gpt-4o-2024-05-13", "GPT-4o (2024-05-13)": "gpt-4o-2024-05-13",
    "GPT-4 Turbo": "gpt-4-turbo-2024-04-09",
    "GPT-4 Turbo (2024-04-09)": "gpt-4-turbo-2024-04-09",
    "DeepSeekCoder": "deepseek-coder-33b-instruct",
    "DeepSeekCoder-33B": "deepseek-coder-33b-instruct",
    "LLaMA3-70B": "meta-llama/Llama-3-70b-chat-hf", "Qwen2.5-32B": "Qwen2.5-32B-Instruct",
    "Qwen3-14B": "Qwen3-14B", "Claude Opus 4.6": "claude-opus-4-6",
    "claude-opus-4-7": "claude-opus-4-7", "Claude Sonnet 4.6": "claude-sonnet-4-6",
    "GPT-4.1": "gpt-4.1-2025-04-14", "gpt-4.1-mini": "gpt-4.1-mini",
    "gpt-5.6-luna": "gpt-5.6-luna", "gptoss-20b": "gpt-oss-20b",
}


def group_of(model, exp):
    # react-gpt4o-2_setbsr uses gpt-4o-2024-08-06: same family, same year -> legacy
    if model in MODERN_MODELS:
        return "modern"
    if model in LEGACY_MODELS:
        return "legacy"
    return "unassigned"


def main():
    inv = {r["experiment"]: r for r in csv.DictReader(open("fresh_runs_inventory.csv"))}
    rows = []
    # modern + interim episodes (detector with the documented LARA adaptation)
    for r in csv.DictReader(open("fresh_fail_after_write.csv")):
        i = inv[r["experiment"]]
        rows.append(dict(source="leaderboard", experiment=r["experiment"],
                         model=r["model"], model_id=MODEL_ID.get(r["model"], r["model"]),
                         code_version=i["code_version"], data_version=i["data_version"],
                         dataset=r["dataset"], task_id=r["task_id"], block=r["block"],
                         write_confirmed=r["write_confirmed"], path=r["path"],
                         detector="fresh_detect2 (+LARA call_api)",
                         group=group_of(r["model"], r["experiment"])))
    # legacy episodes from the first audit, official copies only (deduped)
    for r in csv.DictReader(open("fail_after_write.csv")):
        if r["source"] != "official":
            continue
        i = inv.get(r["experiment"], {})
        rows.append(dict(source="official", experiment=r["experiment"],
                         model=r["model"], model_id=MODEL_ID.get(r["model"], r["model"]),
                         code_version=i.get("code_version", ""),
                         data_version=i.get("data_version", ""),
                         dataset=r["dataset"], task_id=r["task_id"], block=r["block"],
                         write_confirmed=r["confirmed_writes"], path=r["path"],
                         detector="appworld_audit (first audit)",
                         group=group_of(r["model"], r["experiment"])))
    for r in rows:
        r["episode_id"] = f"{r['experiment']}|{r['task_id']}|{r['block']}"
        r["source_run"] = f"{r['experiment']}|{r['task_id']}"
        r["reproducibility"] = "not checked"
        r["repro_note"] = ""
    with open("episode_registry.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    print(f"episodes total: {len(rows)}; unique id: {len({r['episode_id'] for r in rows})}")
    print("\n| group | episodes | runs | configurations | models | data versions |")
    print("|---|--:|--:|--:|--:|---|")
    for g in ("legacy", "modern", "unassigned"):
        gg = [r for r in rows if r["group"] == g]
        if not gg: continue
        print(f"| {g} | {len(gg)} | {len({r['source_run'] for r in gg})} | "
              f"{len({r['experiment'] for r in gg})} | {len({r['model_id'] for r in gg})} | "
              f"{', '.join(sorted({r['data_version'] or '?' for r in gg}))} |")
    # overlap check
    runs = collections.defaultdict(set)
    for r in rows:
        runs[r["source_run"]].add(r["group"])
    both = [k for k, v in runs.items() if len(v) > 1]
    print(f"\nruns that fell into both groups: {len(both)} {both[:3]}")
    print("\ncomposition by model:")
    for g in ("legacy", "modern"):
        c = collections.Counter(r["model_id"] for r in rows if r["group"] == g)
        print(f"  {g}: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))


if __name__ == "__main__":
    main()
