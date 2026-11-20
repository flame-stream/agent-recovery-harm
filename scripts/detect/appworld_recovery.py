#!/usr/bin/env python3
"""
Steps 3-6: recovery classification, consequences, concentration, API contracts.
Rules fixed before inspecting results. New logic marked `# RULE n`.
"""
import ast, csv, json, re, sys, collections, pathlib, hashlib, argparse
import appworld_audit as A

# RULE 1: 28 of the 48 leaderboard experiments are byte-identical republications of
# the official baselines (verified by md5 of environment_io.md over a fixed sample of
# 25 tasks each). The leaderboard copy is dropped; the official one is kept.
DUP_LEADERBOARD = set("""
full_code_refl_deepseekcoder_test_challenge full_code_refl_deepseekcoder_test_normal
full_code_refl_llama3_test_challenge full_code_refl_llama3_test_normal
full_code_refl_gpt4turbo_test_challenge full_code_refl_gpt4turbo_test_normal
full_code_refl_gpt4o_test_challenge full_code_refl_gpt4o_test_normal
ipfuncall_gpt4turbo_test_challenge ipfuncall_gpt4turbo_test_normal
ipfuncall_gpt4o_test_challenge ipfuncall_gpt4o_test_normal
plan_exec_deepseekcoder_test_challenge plan_exec_deepseekcoder_test_normal
plan_exec_llama3_test_challenge plan_exec_llama3_test_normal
plan_exec_gpt4turbo_test_challenge plan_exec_gpt4turbo_test_normal
plan_exec_gpt4o_test_challenge plan_exec_gpt4o_test_normal
react_deepseekcoder_test_challenge react_deepseekcoder_test_normal
react_llama3_test_challenge react_llama3_test_normal
react_gpt4turbo_test_challenge react_gpt4turbo_test_normal
react_gpt4o_test_challenge react_gpt4o_test_normal
""".split())


def is_duplicate(source, experiment):
    return source == "leaderboard" and experiment in DUP_LEADERBOARD


# ---------------- url -> (app, api) ----------------
def _build_url_matchers():
    out = []
    for key, spec in A.API_INDEX.items():
        app, api = key.split(".", 1)
        pat = re.escape(spec["path"])
        pat = re.sub(r'\\\{[^}]*\\\}', r'[^/]+', pat)
        out.append((spec["method"].lower(), re.compile("^" + pat + "$"), app, api))
    # longest path first so that /venmo/transactions/{id} beats /venmo/transactions
    out.sort(key=lambda t: -len(t[1].pattern))
    return out


URL_MATCHERS = _build_url_matchers()


def classify_url(method, url):
    url = (url or "").split("?")[0].rstrip("/") or "/"
    for m, rx, app, api in URL_MATCHERS:
        if m == (method or "").lower() and rx.match(url):
            return app, api
    return None, None


def load_api_calls(task_dir):
    calls = []
    p = task_dir / "logs" / "api_calls.jsonl"
    try:
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            app, api = classify_url(d.get("method"), d.get("url"))
            calls.append(dict(method=d.get("method"), url=d.get("url"),
                              data=d.get("data") or {}, app=app, api=api))
    except Exception:
        pass
    return calls


# RULE 2: block <-> api_calls alignment. api_calls.jsonl is a flat, ordered list for
# the whole run with no block markers. Walk blocks in order and greedily consume
# leading calls whose (app, api) appears in that block's code. Validation metric:
# for blocks that failed with an API error, the LAST consumed call must be that API.
def align(blocks, calls):
    spans, p = [], 0
    for b in blocks:
        names = {(m[0], m[1]) for m in A.APIS_CALL_RE.findall(b["code"])}
        start = p
        while p < len(calls) and (calls[p]["app"], calls[p]["api"]) in names:
            p += 1
        spans.append((start, p))
    return spans, p


def norm_code(code):
    return re.sub(r'\s+', ' ', code).strip()


# RULE 3: argument signature of a write call. Uses the resolved values from
# api_calls.jsonl when the call could be aligned, else the literal source text.
VOLATILE_ARGS = {"access_token", "password", "session_token"}


def arg_sig(data):
    d = {k: v for k, v in (data or {}).items() if k not in VOLATILE_ARGS}
    return hashlib.md5(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]


# RULE 4: undo counterparts used for `compensation`.
UNDO_PREFIXES = ("delete_", "remove_", "cancel_", "clear_", "deny_", "unfollow_",
                 "unlike_", "withdraw_", "revoke_", "archive_")


def is_undo(api):
    return api.startswith(UNDO_PREFIXES)


# RULE 5 (revised after the manual pass): a "creating" write is one whose HTTP method
# is POST -- it adds a new resource, so a successful repeat materialises a SECOND one.
# PUT/PATCH (update) and DELETE are idempotent in effect. The first version used name
# prefixes and missed e.g. splitwise.record_payment, gmail.reply_to_email.
def is_creating(app_api):
    spec = A.API_INDEX.get(app_api)
    return bool(spec) and spec["method"] == "POST"


# ---------------- call signatures ----------------
def _call_nodes(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute)
                    and isinstance(f.value.value, ast.Name) and f.value.value.id == "apis"):
                yield f.value.attr, f.attr, n


def call_sig(code, node):
    """RULE 6: signature of a call = app.api + normalised source text of its keyword
    arguments with volatile ones (access_token/password) removed. Values that are
    variables are therefore compared by EXPRESSION, not by value -- api_calls.jsonl
    could not be aligned to blocks (RULE 2 failed validation, see report)."""
    parts = []
    for kw in node.keywords:
        if kw.arg in VOLATILE_ARGS:
            continue
        try:
            seg = ast.get_source_segment(code, kw.value) or ""
        except Exception:
            seg = ""
        parts.append(f"{kw.arg}={norm_code(seg)}")
    for arg in node.args:
        try:
            seg = ast.get_source_segment(code, arg) or ""
        except Exception:
            seg = ""
        parts.append(norm_code(seg))
    return "|".join(sorted(parts))


def block_calls(code):
    """-> list of (app, api, lineno, sig)"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return [(app, api, n.lineno, call_sig(code, n)) for app, api, n in _call_nodes(tree)]


def confirmed_write_sigs(code, fail_line):
    conf, _ = A.executed_calls(code, fail_line)
    conf_keys = collections.Counter((a, n, l) for a, n, l in conf)
    out = []
    for app, api, line, sig in block_calls(code):
        if conf_keys.get((app, api, line)) and A.is_write(app, api):
            out.append((app, api, line, sig))
    return out


# ---------------- final-DB duplicate evidence ----------------
TS_RE = re.compile(r'^\d{4}-\d{2}-\d{2}[ T]')
INSERT_RE = re.compile(r'^INSERT INTO (\w+)', re.I)


def db_duplicate_groups(task_dir):
    """RULE 7: groups of >=2 INSERTs into one table with identical parameter tuples
    after dropping timestamps and record hashes. Evidence that a duplicated record
    survived into the final DB."""
    groups = collections.Counter()
    dbs = task_dir / "dbs"
    if not dbs.is_dir():
        return groups
    for f in dbs.glob("*.jsonl"):
        app = f.stem
        try:
            for line in open(f):
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                sql = rec[0] if isinstance(rec, list) else ""
                m = INSERT_RE.match(sql or "")
                if not m:
                    continue
                params = rec[1] if len(rec) > 1 else []
                norm = tuple("" if (isinstance(p, str) and (TS_RE.match(p) or len(p) == 12
                             and p.endswith("="))) else p for p in params)
                groups[(app, m.group(1), norm)] += 1
        except Exception:
            continue
    return groups


# ---------------- steps 3-4 ----------------
READ_ONLY = lambda app, api: not A.is_write(app, api) and api not in A.TASK_COMPLETION_APIS


def analyse_episode(blocks, recs, i, task_dir, dup_groups):
    """blocks/recs are parallel lists; i is the index of the fail_after_write block."""
    F, fr = blocks[i], recs[i]
    W = confirmed_write_sigs(F["code"], fr["fail_line"] or None)
    if not W:
        return None
    w_keys = {(a, n) for a, n, l, s in W}
    w_sigs = {(a, n, s) for a, n, l, s in W}
    # RULE 8 (revised after the manual pass): the recovery window is EVERY block after
    # F to the end of the run. The first version stopped at the next fail_after_write
    # block, which made a long chain of repeated failures look like `abandon` although
    # the very next block was the recovery attempt. Episodes therefore overlap; that is
    # intended -- one failed write can be recovered from more than once.
    window = list(range(i + 1, len(blocks)))
    next_is_faw = int(i + 1 < len(blocks) and recs[i + 1]["cls"] == "fail_after_write")

    flags = dict(full_rerun=0, modified_rerun_overlap=0, continuation=0,
                 state_check=0, compensation=0, abandon=0)
    repeat_block = None
    repeat_sig_match = 0
    first_api_block = None
    normF = norm_code(F["code"])
    unconfirmed_writes = {(a, n) for a, n, l, s in block_calls(F["code"])
                          if A.is_write(a, n)} - w_keys

    for j in window:
        calls = block_calls(blocks[j]["code"])
        if not calls:
            continue
        if first_api_block is None:
            first_api_block = j
            if all(READ_ONLY(a, n) for a, n, l, s in calls):
                flags["state_check"] = 1
        keys = {(a, n) for a, n, l, s in calls}
        sigs = {(a, n, s) for a, n, l, s in calls}
        if repeat_block is None:
            if sigs & w_sigs:
                repeat_block, repeat_sig_match = j, 1
            elif keys & w_keys:
                repeat_block, repeat_sig_match = j, 0
        if norm_code(blocks[j]["code"]) == normF:
            flags["full_rerun"] = 1
        if (sigs & w_sigs) or (keys & w_keys):
            flags["modified_rerun_overlap"] = 1
        if keys & unconfirmed_writes and not (keys & w_keys):
            flags["continuation"] = 1
        for a, n, l, s in confirmed_write_sigs(blocks[j]["code"],
                                               recs[j]["fail_line"] or None):
            if is_undo(n) and a in {x[0] for x in w_keys}:
                flags["compensation"] = 1
    if first_api_block is None:
        flags["abandon"] = 1

    # RULE 8 priority for the primary class
    for cls in ("abandon", "full_rerun", "modified_rerun_overlap", "compensation",
                "continuation", "state_check"):
        if flags[cls]:
            primary = cls
            break
    else:
        primary = "other"

    # --- step 4 consequences ---
    repeated = int(repeat_block is not None)
    new_effect = 0
    repeated_api = ""
    if repeat_block is not None:
        rc = confirmed_write_sigs(blocks[repeat_block]["code"],
                                  recs[repeat_block]["fail_line"] or None)
        for a, n, l, s in rc:
            if (a, n) in w_keys:
                new_effect = 1
                repeated_api = f"{a}.{n}"
                break
        if not repeated_api:
            for a, n, l, s in block_calls(blocks[repeat_block]["code"]):
                if (a, n) in w_keys:
                    repeated_api = f"{a}.{n}"
                    break
    creating = int(bool(repeated_api) and is_creating(repeated_api))
    harmful_candidate = int(repeated and new_effect and creating)
    dup_in_db = int(any(v >= 2 for v in dup_groups.values()))
    transient = int(harmful_candidate and (flags["compensation"] or not dup_in_db))
    # how the service answered the repeat (step 6)
    repeat_outcome = ""
    if repeat_block is not None:
        rr = recs[repeat_block]
        if rr["status"] == "success":
            repeat_outcome = "materialised"
        elif rr["fail_kind"] == "api_error" and rr["fail_api"] == repeated_api:
            repeat_outcome = f"rejected_{rr['http_status']}"
        elif new_effect:
            repeat_outcome = "materialised"
        else:
            repeat_outcome = "unknown"
    return dict(
        block=fr["block"], fail_line=fr["fail_line"], fail_kind=fr["fail_kind"],
        fail_api=fr["fail_api"], http_status=fr["http_status"],
        n_confirmed_writes=len(W), next_is_faw=next_is_faw,
        confirmed_writes=";".join(f"{a}.{n}" for a, n, l, s in W),
        window_len=len(window), primary_class=primary, **flags,
        repeat_confirmed_write=repeated, repeat_sig_exact=repeat_sig_match,
        repeat_block=(recs[repeat_block]["block"] if repeat_block is not None else ""),
        repeat_distance=(repeat_block - i if repeat_block is not None else ""),
        repeated_api=repeated_api, new_effect=new_effect,
        creating_api=creating, harmful_candidate=harmful_candidate,
        dup_insert_in_final_db=dup_in_db, transient=transient,
        repeat_outcome=repeat_outcome)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", default="blocks.csv")
    a = ap.parse_args()
    rows = list(csv.DictReader(open(a.blocks)))
    byrun = collections.defaultdict(list)
    for r in rows:
        if is_duplicate(r["source"], r["experiment"]):
            continue
        byrun[r["path"]].append(r)
    print("runs (dedup):", len(byrun))
    out, faw_runs = [], 0
    for path, recs in byrun.items():
        recs.sort(key=lambda r: int(r["block"]))
        idx = [i for i, r in enumerate(recs) if r["cls"] == "fail_after_write"]
        if not idx:
            continue
        faw_runs += 1
        td = pathlib.Path(path)
        blocks = A.parse_blocks(td / "logs" / "environment_io.md")
        bymap = {b["index"]: b for b in blocks}
        blist = [bymap.get(int(r["block"]), dict(code="", output="")) for r in recs]
        rlist = [dict(r, fail_line=(int(r["fail_line"]) if r["fail_line"] else None))
                 for r in recs]
        dupg = db_duplicate_groups(td)
        for i in idx:
            ep = analyse_episode(blist, rlist, i, td, dupg)
            if ep is None:
                continue
            base = {k: recs[i][k] for k in ("source", "experiment", "agent", "model",
                                            "dataset", "task_id", "scenario", "difficulty",
                                            "task_success")}
            out.append(dict(base, path=path, **ep))
    with open("fail_after_write.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    print(f"wrote fail_after_write.csv: {len(out)} episodes in {faw_runs} runs")


if __name__ == "__main__":
    main()
