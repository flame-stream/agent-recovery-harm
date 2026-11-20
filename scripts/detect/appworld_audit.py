#!/usr/bin/env python3
"""
AppWorld audit: partial execution of a code block and recovery.

Marking rules are fixed here BEFORE looking at any results.

Sources: official AppWorld experiment outputs (experiment-outputs-0.1.3.bundle) and
the AppWorld leaderboard bundles. One "run" = one task attempt
(agent x model x dataset x task_id).

Evidence available per run:
  logs/environment_io.md   code block + its stdout/traceback for every world.execute()
  logs/api_calls.jsonl     every HTTP call the agent made: {method, url, data}  (NO responses)
  dbs/{app}.jsonl          SQL diff of the final DB vs the base DB
  evaluation/report.md     official per-task evaluator report
  evaluations/{ds}.json    per-task success flag

Because api_calls.jsonl carries no responses and stdout is DISCARDED when a block
fails, the outcome of an individual API call is reconstructed from the block's
traceback plus static control-flow reasoning (see executed_calls).
"""
import ast, csv, json, re, sys, collections, pathlib, argparse

# ---------------- fixed vocabulary ----------------
AUTH_APIS = {"login", "logout", "signup", "send_verification_code", "verify_account",
             "send_password_reset_code", "reset_password"}
TASK_COMPLETION_APIS = {"complete_task"}

def load_write_apis(path="write_apis.txt"):
    return set(open(path).read().split())

WRITE_APIS = load_write_apis()                      # 237 state-changing APIs
API_INDEX = json.load(open("api_index.json"))       # "app.api" -> {path, method}

# ---------------- environment_io parsing ----------------
SPLIT_RE = re.compile(r'^### Environment Interaction (\d+)\n-+\n', re.M)
FENCE_RE = re.compile(r'```(?:python)?\n(.*?)\n?```', re.S)
FAIL_PREFIX = "Execution failed. Traceback:"
PYIN_LINE_RE = re.compile(r'File "<python-input>", line (\d+)')
HTTP_RE = re.compile(r'Response status code is (\d+):\s*(\{.*|\[.*)?', re.S)
EXC_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*):', re.M)
APIS_CALL_RE = re.compile(r'\bapis\.([a-z_]+)\.([a-z_0-9]+)\s*\(')


def parse_blocks(path):
    """-> list of dicts: {index, code, output}"""
    text = pathlib.Path(path).read_text(errors="replace")
    parts = SPLIT_RE.split(text)
    out = []
    for i in range(1, len(parts) - 1, 2):
        fences = FENCE_RE.findall(parts[i + 1])
        if len(fences) < 2:
            out.append(dict(index=int(parts[i]), code=fences[0] if fences else "",
                            output="", malformed=True))
            continue
        out.append(dict(index=int(parts[i]), code=fences[0], output=fences[1], malformed=False))
    return out


def block_outcome(output):
    """-> dict(status, fail_kind, fail_line, http_status, fail_stmt)"""
    if not output.startswith(FAIL_PREFIX):
        return dict(status="success", fail_kind="", fail_line=None, http_status="", fail_stmt="")
    lines = PYIN_LINE_RE.findall(output)
    fail_line = int(lines[0]) if lines else None      # module-level frame
    m = HTTP_RE.search(output)
    if m:
        kind, http = "api_error", m.group(1)
    else:
        excs = [e for e in EXC_RE.findall(output) if e.endswith(("Error", "Exception"))]
        kind, http = (excs[-1] if excs else "unknown_error"), ""
        if fail_line is None:
            kind = "syntax_or_no_frame"
    stmt = ""
    if fail_line is not None:
        mm = re.search(r'File "<python-input>", line %d, in [^\n]*\n(.*?)\n' % fail_line, output)
        stmt = (mm.group(1).strip() if mm else "")[:160]
    return dict(status="failed", fail_kind=kind, fail_line=fail_line,
                http_status=http, fail_stmt=stmt)


# ---------------- static control-flow reasoning ----------------
SIMPLE_STMTS = (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr, ast.Return,
                ast.Delete, ast.Assert, ast.Raise, ast.Pass, ast.Import, ast.ImportFrom,
                ast.Global, ast.Nonlocal)
# `with` bodies always execute; try/if/for/while bodies may not; def/class bodies
# execute only if called/instantiated.
ALWAYS_ENTERED = (ast.With, ast.AsyncWith)
MAYBE_ENTERED = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
                 ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _calls_in(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute)
                    and isinstance(f.value.value, ast.Name) and f.value.value.id == "apis"):
                yield (f.value.attr, f.attr, n.lineno)


def executed_calls(code, fail_line):
    """Return (confirmed, uncertain) lists of (app, api, lineno).

    confirmed = calls that MUST have run and returned without raising, because
                execution later reached `fail_line` (or the block finished).
    uncertain = calls that may or may not have run (inside a branch/loop/def that
                does not contain the failure point).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return [], []
    confirmed, uncertain = [], []

    def contains(stmt, line):
        return stmt.lineno <= line <= (getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno)

    def walk_body(body, line):
        """line=None -> whole body executed (successful block)."""
        for stmt in body:
            end = getattr(stmt, "end_lineno", stmt.lineno) or stmt.lineno
            if line is not None and contains(stmt, line):
                # the failing statement itself: descend into the sub-body holding the line
                if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
                                     ast.With, ast.AsyncWith)):
                    for attr in ("body", "orelse", "finalbody", "handlers"):
                        sub = getattr(stmt, attr, None) or []
                        if attr == "handlers":
                            for h in sub:
                                if any(contains(s, line) for s in h.body):
                                    walk_body(h.body, line)
                            continue
                        if any(contains(s, line) for s in sub):
                            walk_body(sub, line)
                return                                   # nothing after the failure ran
            if line is not None and stmt.lineno > line:
                return
            # statement completed before the failure (or block succeeded)
            if isinstance(stmt, SIMPLE_STMTS):
                confirmed.extend(_calls_in(stmt))
            elif isinstance(stmt, ALWAYS_ENTERED):
                walk_body(stmt.body, None)
            else:
                uncertain.extend(_calls_in(stmt))
    walk_body(tree.body, fail_line)
    return confirmed, uncertain


def is_write(app, api):
    return f"{app}.{api}" in WRITE_APIS


# ---------------- per-run analysis ----------------
def analyse_run(task_dir):
    env_io = task_dir / "logs" / "environment_io.md"
    blocks = parse_blocks(env_io)
    recs = []
    for b in blocks:
        oc = block_outcome(b["output"])
        # FIX (found in the manual pass): a failed block with no <python-input> frame
        # was rejected BEFORE execution (sandbox module guard, syntax error), so nothing
        # ran. Passing fail_line=None would have meant "the whole body executed".
        if oc["status"] == "failed" and oc["fail_line"] is None:
            conf, unc = [], [(a, n, 0) for a, n in APIS_CALL_RE.findall(b["code"])]
        else:
            conf, unc = executed_calls(
                b["code"], oc["fail_line"] if oc["status"] == "failed" else None)
        sites = [(m[0], m[1], 0) for m in APIS_CALL_RE.findall(b["code"])]
        w_conf = [c for c in conf if is_write(c[0], c[1])]
        w_unc = [c for c in unc if is_write(c[0], c[1])]
        w_sites = [s for s in sites if is_write(s[0], s[1])]
        if oc["status"] == "success":
            cls = "success"
        elif w_conf:
            cls = "fail_after_write"
        elif w_unc:
            cls = "fail_unknown"
        else:
            cls = "fail_before_write"
        recs.append(dict(
            block=b["index"], status=oc["status"], fail_kind=oc["fail_kind"],
            fail_line=oc["fail_line"] or "", http_status=oc["http_status"],
            fail_stmt=oc["fail_stmt"], cls=cls,
            n_calls_confirmed=len(conf), n_calls_uncertain=len(unc),
            n_write_sites=len(w_sites), n_write_confirmed=len(w_conf),
            n_write_uncertain=len(w_unc),
            write_confirmed=";".join(f"{a}.{n}@{l}" for a, n, l in w_conf),
            write_uncertain=";".join(f"{a}.{n}@{l}" for a, n, l in w_unc),
            fail_api=_fail_api(oc, b["code"]),
            code_len=len(b["code"].splitlines()),
        ))
    return recs, blocks


def _fail_api(oc, code):
    if oc["status"] != "failed" or oc["fail_kind"] != "api_error":
        return ""
    m = APIS_CALL_RE.search(oc["fail_stmt"] or "")
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    # traceback prints only the first line of a multi-line call; fall back to the
    # call site on the failing line of the code
    if oc["fail_line"]:
        lines = code.splitlines()
        if 0 < oc["fail_line"] <= len(lines):
            m = APIS_CALL_RE.search(lines[oc["fail_line"] - 1])
            if m:
                return f"{m.group(1)}.{m.group(2)}"
    return ""


# ---------------- source inventory (step 1) ----------------
REQUIRED = ["logs/environment_io.md", "logs/api_calls.jsonl", "version/code.txt"]
OPTIONAL = ["evaluation/report.md", "dbs/venmo.jsonl"]


def iter_runs(roots):
    """Yield (source, experiment, task_dir)."""
    for source, root in roots:
        root = pathlib.Path(root)
        for meta in sorted(root.rglob("metadata.json")):
            exp = meta.parent
            tasks_dir = exp / "tasks"
            if not tasks_dir.is_dir():
                continue
            for td in sorted(p for p in tasks_dir.iterdir() if p.is_dir()):
                yield source, str(exp.relative_to(root)), td


def inventory(roots, out_csv="sources.csv"):
    rows = []
    for source, exp, td in iter_runs(roots):
        have = {p: (td / p).exists() for p in REQUIRED + OPTIONAL}
        n_db = len(list((td / "dbs").glob("*.jsonl"))) if (td / "dbs").is_dir() else 0
        ver = ""
        if (td / "version" / "code.txt").exists():
            ver = (td / "version" / "code.txt").read_text().strip()[:20]
        rows.append(dict(source=source, experiment=exp, task_id=td.name,
                         code_version=ver, n_db_files=n_db,
                         **{p.replace("/", "_"): int(v) for p, v in have.items()}))
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return rows


# ---------------- run-level metadata ----------------
_GT_CACHE = {}


def task_meta(task_id):
    if task_id in _GT_CACHE:
        return _GT_CACHE[task_id]
    d = pathlib.Path("data/tasks") / task_id / "ground_truth" / "metadata.json"
    m = {}
    if d.exists():
        try:
            m = json.load(open(d))
        except Exception:
            m = {}
    out = dict(difficulty=m.get("difficulty", ""), num_apps=m.get("num_apps", ""),
               gt_api_calls=m.get("num_api_calls", ""))
    _GT_CACHE[task_id] = out
    return out


def exp_meta(exp_dir):
    md = exp_dir / "metadata.json"
    m = json.load(open(md)) if md.exists() else {}
    agent = (m.get("method") or {}).get("name", "?")
    model = (m.get("llm") or {}).get("name", "?")
    dataset = m.get("dataset", "?")
    evals = {}
    ev = exp_dir / "evaluations" / f"{dataset}.json"
    if ev.exists():
        try:
            evals = (json.load(open(ev)) or {}).get("individual", {})
        except Exception:
            evals = {}
    return agent, model, dataset, evals


# ---------------- stage: blocks ----------------
# A run is USABLE only if all required artifacts are present AND the trace actually
# shows in-block execution: >=1 parsed block and >=1 logged API call that is not
# supervisor.complete_task. (Rule fixed before looking at results.)
def stage_blocks(roots, out_csv="blocks.csv", runs_csv="runs.csv"):
    block_rows, run_rows = [], []
    exp_cache = {}
    for source, exp, td in iter_runs(roots):
        exp_dir = td.parent.parent
        if exp_dir not in exp_cache:
            exp_cache[exp_dir] = exp_meta(exp_dir)
        agent, model, dataset, evals = exp_cache[exp_dir]
        task_id = td.name
        n_api_calls = 0
        n_nontrivial = 0
        try:
            for line in open(td / "logs" / "api_calls.jsonl"):
                line = line.strip()
                if not line:
                    continue
                n_api_calls += 1
                if "/supervisor/task_completion" not in line and "complete_task" not in line:
                    n_nontrivial += 1
        except Exception:
            pass
        try:
            recs, _ = analyse_run(td)
        except Exception as e:
            recs = []
        usable = int(len(recs) >= 1 and n_nontrivial >= 1)
        ev = evals.get(task_id) or {}
        tm = task_meta(task_id)
        base = dict(source=source, experiment=exp, agent=agent, model=model,
                    dataset=dataset, task_id=task_id, scenario=task_id.split("_")[0],
                    difficulty=tm["difficulty"], task_success=int(bool(ev.get("success"))),
                    usable=usable)
        run_rows.append(dict(base, n_blocks=len(recs), n_api_calls=n_api_calls,
                             n_api_calls_nontrivial=n_nontrivial, path=str(td)))
        if not usable:
            continue
        for r in recs:
            block_rows.append(dict(base, path=str(td), **r))
    for name, rows in ((out_csv, block_rows), (runs_csv, run_rows)):
        with open(name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        print(f"wrote {name}: {len(rows)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="inventory")
    a = ap.parse_args()
    roots = [("official", "outputs"), ("leaderboard", "lb_outputs")]
    if a.stage == "blocks":
        stage_blocks(roots)
    if a.stage == "inventory":
        rows = inventory(roots)
        print("runs:", len(rows))
        c = collections.Counter((r["source"], tuple(int(r[p.replace('/', '_')]) for p in REQUIRED))
                                for r in rows)
        for k, v in c.most_common():
            print(f"  {v:6d}  source={k[0]}  has(env_io,api_calls,version)={k[1]}")


if __name__ == "__main__":
    main()
