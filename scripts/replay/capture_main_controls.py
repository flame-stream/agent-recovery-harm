#!/usr/bin/env python3
"""Recompute the step-1 replay controls uniformly for all 200 captured episodes, from the
frozen capture and the replay's own AppWorld log, then freeze (SHA256SUMS).

Why a separate pass: two control rules were refined after the first 25 legacy episodes
(before any matching was run), and the refined rules must apply to every episode alike:
  ctl_hist  the replay's HTTP log (method, url, data without access tokens) equals the
            historical api_calls.jsonl over the prefix and the block (boundary = AppWorld's
            own request counter at the end of the block, `http_n`), AND the first call
            after the block also agrees (or both logs end there). The first version
            compared only the prefix and passed an episode whose replay made no calls at all.
  ctl_fail  the block fails as in the historical environment_io.md and the historical last
            exception line is a prefix of the replayed one (legacy logs cut the message
            to "Exception").
  ctl_snapB unchanged (computed in capture_main.py).
replay_mismatch = not (ctl_snapB and ctl_hist and ctl_fail), as in the pilot.
Output: reports/counterfactual_main/controls_capture.json, early_calls_main_SHA256SUMS
"""
import csv, glob, hashlib, json, pathlib

R = pathlib.Path("reports/counterfactual_main")
EC = R / "early_calls_main"
STAND = {"0.1.0": pathlib.Path("replay_root"), "0.2.0": pathlib.Path("stand020")}
csv.field_size_limit(10**9)


def norm(line):
    d = json.loads(line)
    data = {k: v for k, v in (d.get("data") or {}).items() if k not in ("access_token", "file_system_access_token")}
    return [d.get("method"), d.get("url"), data]


def main():
    eps = {r["episode_id"].replace("/", "~").replace("|", "__"): r
           for f in ("random_sample_legacy.csv", "random_sample_modern.csv") for r in csv.DictReader(open(f))}
    raw = {}
    for f in sorted(glob.glob(str(EC / "_controls_*.json"))):
        for r in json.load(open(f)):
            raw[r["key"]] = r
    out = []
    for key in sorted(eps):
        ep = eps[key]
        r = dict(raw.get(key, dict(key=key, error="not captured")))
        r["group"], r["source_run"] = ep["group"], ep["source_run"]
        calls = [json.loads(l) for l in open(EC / f"{key}.jsonl")] if (EC / f"{key}.jsonl").exists() else []
        exp = "cfm_" + key[-70:].replace("~", "_")
        mine_p = STAND[ep["data_version"]] / "experiments" / "outputs" / exp / "tasks" / ep["task_id"] / "logs" / "api_calls.jsonl"
        hist_p = pathlib.Path(ep["path"]) / "logs" / "api_calls.jsonl"
        if "error" in r or not mine_p.exists():
            r.update(ctl_hist=0, ctl_fail=int(r.get("ctl_fail", 0)), ctl_snapB=int(r.get("ctl_snapB", 0)))
            r["ctl_note"] = r.get("error", "no replay log")
        else:
            mine = [norm(l) for l in open(mine_p) if l.strip()]
            hist = [norm(l) for l in open(hist_p) if l.strip()]
            nb = r.get("n_http_through_block")
            if nb is None:
                nb = calls[r["n_through_block"] - 1]["http_n"] if r.get("n_through_block") else 0
            f = next((k for k, (x, y) in enumerate(zip(mine[:nb], hist[:nb])) if x != y), None)
            if f is None and min(len(mine), nb) != min(len(hist), nb):
                f = min(len(mine), len(hist), nb)
            nxt_ok = (len(hist) == nb) or (len(mine) > nb and len(hist) > nb and mine[nb] == hist[nb])
            r["ctl_hist"] = int(f is None and nxt_ok and len(hist) >= nb)
            r["ctl_hist_first_diff"] = f if f is not None else (None if nxt_ok else nb)
            g = next((k for k, (x, y) in enumerate(zip(mine, hist)) if x != y), None)
            if g is None and len(mine) != len(hist):
                g = min(len(mine), len(hist))
            r["ctl_hist_full"], r["ctl_hist_full_first_diff"] = int(g is None), g
            bx, ox = r.get("block_exc") or "", r.get("orig_exc") or ""
            r["ctl_fail"] = int(r.get("block_failed") == r.get("orig_block_failed") and
                                (not r.get("block_failed") or bx.startswith(ox)))
            r["n_http_through_block"], r["n_http"], r["n_hist"] = nb, len(mine), len(hist)
        r["replay_mismatch"] = int(not (r.get("ctl_snapB") and r.get("ctl_hist") and r.get("ctl_fail")))
        r.pop("trace", None)
        out.append(r)
    json.dump(out, open(R / "controls_capture.json", "w"), ensure_ascii=False, indent=1, sort_keys=True)
    lines = []
    for p in sorted(EC.glob("*.jsonl")) + [R / "controls_capture.json", R / "id_fields.json"]:
        lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(R)}")
    (R / "early_calls_main_SHA256SUMS").write_text("\n".join(lines) + "\n")
    n = len(out)
    print(f"episodes {n}: snapB {sum(r.get('ctl_snapB', 0) for r in out)}, hist {sum(r['ctl_hist'] for r in out)}, "
          f"fail {sum(r['ctl_fail'] for r in out)}, B and log {sum(bool(r.get('ctl_snapB') and r['ctl_hist']) for r in out)}, "
          f"all three {sum(not r['replay_mismatch'] for r in out)}")


if __name__ == "__main__":
    main()
