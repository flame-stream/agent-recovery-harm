#!/usr/bin/env python3
"""Step 2+4: replay the sampled episodes and measure the actual state change."""
import csv, json, re, sys, pathlib, collections, time, hashlib
sys.path.insert(0, ".")
import replay_lib as R

SPLIT = re.compile(r'^### Environment Interaction (\d+)\n-+\n', re.M)
FENCE = re.compile(r'```(?:python)?\n(.*?)\n?```', re.S)
VOLATILE = {"access_token", "password", "session_token"}
PYIN = re.compile(r'File "<python-input>", line (\d+)')
HTTP = re.compile(r'Response status code is (\d+)')
EXC = re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*)(?::|$)', re.M)


JWT = re.compile(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+')


def mask(s):
    """Access tokens are JWTs whose `exp` claim encodes wall-clock login time, so they
    can never match across a replay. They carry no state information."""
    return JWT.sub("<JWT>", s or "")


def semantic_key(out):
    """Fidelity key that ignores presentation-only differences: Python 3.12 inlines
    comprehension frames (PEP 709) and appworld 0.1.0 renders some exception messages
    differently than the recording did. Compared instead: outcome, the deepest
    <python-input> line, the exception class and the HTTP status."""
    o = mask(out or "")
    if not o.startswith("Execution failed. Traceback:"):
        return ("ok", R.NORM(o))
    lines = PYIN.findall(o)
    line = lines[-1] if lines else ""
    http = (HTTP.search(o) or [None, ""])[1] if HTTP.search(o) else ""
    excs = [e for e in EXC.findall(o) if e.endswith(("Error", "Exception"))]
    return ("fail", line, http, excs[-1] if excs else "")
OUT = pathlib.Path("../state_diffs"); OUT.mkdir(exist_ok=True)


def load_blocks(path):
    txt = (pathlib.Path(path) / "logs" / "environment_io.md").read_text(errors="replace")
    parts = SPLIT.split(txt); out = []
    for i in range(1, len(parts) - 1, 2):
        f = FENCE.findall(parts[i + 1])
        out.append(dict(num=int(parts[i]), code=f[0] if f else "", out=f[1] if len(f) > 1 else ""))
    return out


def calls_delta(before, after):
    b = collections.Counter(before); out = []
    for c in after:
        if b[c]:
            b[c] -= 1
        else:
            out.append(c)
    return out


def parse_calls(lines):
    out = []
    for l in lines:
        try:
            d = json.loads(l)
        except Exception:
            continue
        data = {k: v for k, v in (d.get("data") or {}).items() if k not in VOLATILE}
        out.append(dict(method=d.get("method"), url=d.get("url"), data=data))
    return out


def url_api(method, url, index):
    import appworld_recovery_urls as U
    return U.classify(method, url)


def main():
    sys.path.insert(0, "..")
    import appworld_recovery as AR          # url -> (app, api) matcher
    sample = list(csv.DictReader(open("../replay_sample.csv")))
    rows = []
    for k, ep in enumerate(sample, 1):
        t0 = time.time()
        src = pathlib.Path("..") / ep["path"]
        blocks = load_blocks(src)
        nums = [b["num"] for b in blocks]
        pos = {n: i for i, n in enumerate(nums)}
        fi = pos.get(int(ep["block"]))
        rep = pos.get(int(ep["repeat_block"])) if ep["repeat_block"] else None
        if fi is None:
            rows.append(dict(ep_id=k, status="no_block")); continue
        last = len(blocks) - 1
        stops = {max(fi - 1, 0), fi, last}
        if rep is not None:
            stops |= {max(rep - 1, 0), rep}
        res = R.replay(ep["task_id"], [b["code"] for b in blocks], f"rep_{k}", stops)
        # fidelity
        first_mismatch = first_mismatch_strict = None
        for i, b in enumerate(blocks):
            if i >= len(res["outputs"]):
                first_mismatch = first_mismatch_strict = i + 1; break
            if first_mismatch_strict is None and R.NORM(mask(b["out"])) != R.NORM(mask(res["outputs"][i])):
                first_mismatch_strict = i + 1
            if semantic_key(b["out"]) != semantic_key(res["outputs"][i]):
                first_mismatch = i + 1; break
        faithful_to_fail = first_mismatch is None or first_mismatch > fi + 1
        faithful_to_repeat = first_mismatch is None or (rep is not None and first_mismatch > rep + 1)
        snaps, acalls = res["snapshots"], res.get("api_calls", {})
        d_fail = R.snapshot_diff(snaps.get(max(fi - 1, 0), {}), snaps.get(fi, {}))
        d_rep = (R.snapshot_diff(snaps.get(max(rep - 1, 0), {}), snaps.get(rep, {}))
                 if rep is not None else {})
        d_final = R.snapshot_diff(snaps.get(fi, {}), snaps.get(last, {}))
        c_fail = parse_calls(calls_delta(acalls.get(max(fi - 1, 0), []), acalls.get(fi, [])))
        c_rep = (parse_calls(calls_delta(acalls.get(max(rep - 1, 0), []), acalls.get(rep, [])))
                 if rep is not None else [])
        for c in c_fail + c_rep:
            c["app"], c["api"] = AR.classify_url(c["method"], c["url"])
        tgt = ep["repeated_api"]
        f_calls = [c for c in c_fail if f"{c['app']}.{c['api']}" == tgt]
        r_calls = [c for c in c_rep if f"{c['app']}.{c['api']}" == tgt]
        args_cmp = "n/a"
        if tgt and f_calls and r_calls:
            fv = json.dumps(f_calls[-1]["data"], sort_keys=True)
            rv = json.dumps(r_calls[0]["data"], sort_keys=True)
            args_cmp = "same" if fv == rv else "different"
        elif tgt:
            args_cmp = "incomparable"
        json.dump(dict(episode=ep, first_mismatch=first_mismatch,
                       diff_failing_block=d_fail, diff_repeat_block=d_rep,
                       diff_after_fail_to_end=d_final,
                       calls_failing_block=c_fail, calls_repeat_block=c_rep,
                       replay_error=res["error"]),
                  open(OUT / f"ep_{k:03d}.json", "w"), indent=1)
        rows.append(dict(
            ep_id=k, task_id=ep["task_id"], agent=ep["agent"], model=ep["model"],
            family=ep["_family"], primary_class=ep["primary_class"],
            fail_block=ep["block"], repeat_block=ep["repeat_block"],
            repeated_api=tgt, old_rule_harmful=ep["harmful_candidate"],
            old_rule_new_effect=ep["new_effect"], old_rule_transient=ep["transient"],
            status="ok" if not res["error"] else "replay_error",
            replay_error=res["error"][:120], first_mismatch=first_mismatch or "",
            first_mismatch_strict=first_mismatch_strict or "",
            faithful_to_fail=int(faithful_to_fail), faithful_to_repeat=int(faithful_to_repeat),
            args_by_value=args_cmp,
            n_calls_failing=len(c_fail), n_calls_repeat=len(c_rep),
            diff_failing=json.dumps(R.summarise_diff(d_fail)),
            diff_repeat=json.dumps(R.summarise_diff(d_rep)),
            diff_repeat_rows=sum(x["n"] for x in R.summarise_diff(d_rep)),
            diff_to_end=json.dumps(R.summarise_diff(d_final)),
            secs=round(time.time() - t0, 1)))
        print(f"{k:3d}/{len(sample)} {ep['task_id']:11s} fam={ep['_family']:12s} "
              f"mismatch={first_mismatch} repeat={ep['repeat_block'] or '-':>3s} "
              f"args={args_cmp:12s} repeat_diff={R.summarise_diff(d_rep)} {time.time()-t0:.1f}s",
              flush=True)
    with open("../replay_episodes.csv", "w", newline="") as f:
        cols = sorted({c for r in rows for c in r})
        cols = ["ep_id", "task_id", "family", "primary_class", "repeated_api"] + [c for c in cols if c not in ("ep_id","task_id","family","primary_class","repeated_api")]
        w = csv.DictWriter(f, fieldnames=cols, restval=""); w.writeheader(); w.writerows(rows)
    print("wrote ../replay_episodes.csv:", len(rows))


if __name__ == "__main__":
    main()
