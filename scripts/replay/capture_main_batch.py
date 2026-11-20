#!/usr/bin/env python3
"""Runner for capture_main.py: one subprocess per episode, hard wall-clock kill
(TIMEOUT declared before any result was read). A killed episode is recorded with
replay_mismatch=1 and reason, never dropped. Resumable.
Env: PROJ, STAND, PYBIN, DATAVER (0.1.0 | 0.2.0), optional ONLY (substring of the key).
"""
import csv, json, os, pathlib, subprocess, sys

PROJ = pathlib.Path(os.environ["PROJ"]).resolve()
STAND = pathlib.Path(os.environ["STAND"]).resolve()
PY, DV = os.environ["PYBIN"], os.environ["DATAVER"]
TIMEOUT = float(os.environ.get("EPISODE_TIMEOUT", "1500"))
csv.field_size_limit(10**9)
OUT = PROJ / "reports" / "counterfactual_main" / "early_calls_main"
OUT.mkdir(parents=True, exist_ok=True)
cp = OUT / f"_controls_{DV}.json"
done = {r["key"]: r for r in json.load(open(cp))} if cp.exists() else {}
eps = [r for f in ("random_sample_legacy.csv", "random_sample_modern.csv")
       for r in csv.DictReader(open(PROJ / f)) if r["data_version"] == DV]
for n, ep in enumerate(eps, 1):
    key = ep["episode_id"].replace("/", "~").replace("|", "__")
    if key in done or (os.environ.get("ONLY") and os.environ["ONLY"] not in key):
        continue
    env = dict(os.environ, PROJ=str(PROJ), STAND=str(STAND))
    try:
        out = subprocess.run([PY, str(PROJ / "capture_main.py"), json.dumps(ep, ensure_ascii=False)],
                             cwd=str(STAND), env=env, capture_output=True, text=True, timeout=TIMEOUT)
        line = [l for l in out.stdout.splitlines() if l.startswith("RESULT ")]
        r = json.loads(line[-1][7:]) if line else dict(
            key=key, episode_id=ep["episode_id"], replay_mismatch=1, ctl_snapB=0, ctl_hist=0, ctl_fail=0,
            error=(out.stderr.strip().splitlines() or ["no output"])[-1][:200])
    except subprocess.TimeoutExpired:
        r = dict(key=key, episode_id=ep["episode_id"], replay_mismatch=1, ctl_snapB=0, ctl_hist=0,
                 ctl_fail=0, error=f"time limit {TIMEOUT:.0f} s")
    r.update(group=ep["group"], data_version=DV, source_run=ep["source_run"])
    done[key] = r
    json.dump(list(done.values()), open(cp, "w"), ensure_ascii=False, indent=1)
    print(f"[{n}/{len(eps)}] {key[-60:]} calls={r.get('n_calls')} snapB={r.get('ctl_snapB')} "
          f"hist={r.get('ctl_hist')} fail={r.get('ctl_fail')} snapC={r.get('ctl_snapC')} "
          f"full={r.get('ctl_hist_full')} {str(r.get('error', ''))[:80]}", flush=True)
