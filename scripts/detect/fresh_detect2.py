#!/usr/bin/env python3
"""Steps 1c+2: re-detect modern/interim runs with two documented detector
adaptations, and assign a confirmation level to every fail_after_write record.

DETECTOR CHANGES vs the first audit (both flagged in the report):
 (1) LARA MAS routes every API through its own helper
     `call_api('<app>', '<api>', token, **kw)`; the original regex `apis.<app>.<api>(`
     sees none of it. A second pattern is added. No other agent on disk uses a wrapper.
 (2) task_success: IBM-HCL-GP ships no `evaluations/<split>.json`, only per-task
     `evaluation/report.md`. Success is recovered from "Num Failed Tests : 0" there.
The write-API dictionary itself is unchanged: every app.api seen in the modern runs
is already in write_apis.txt (checked against api_calls.jsonl -> 0 unknown endpoints).
"""
import ast, csv, collections, json, math, pathlib, re, statistics, sys
sys.path.insert(0, ".")
import appworld_audit as A
csv.field_size_limit(10**9)

WRAPPER = re.compile(r"\bcall_api\s*\(\s*['\"]([a-z_]+)['\"]\s*,\s*['\"]([a-z_0-9]+)['\"]")
API_INDEX = json.load(open("api_index.json"))
ROUTES = [(re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", s["path"]) + "$"),
           s["method"].lower(), n) for n, s in API_INDEX.items()]


def route_of(url, method):
    u = (url or "").split("?")[0]
    u = u[:-1] if len(u) > 1 and u.endswith("/") else u
    m = (method or "get").lower()
    for rx, mm, name in ROUTES:
        if mm == m and rx.match(u):
            return name
    return None


_orig_calls_in = A._calls_in


def _calls_in(node):
    """Original apis.<app>.<api>(...) plus LARA's call_api('<app>', '<api>', ...).
    Patched into the detector so the existing AST reasoning (confirmed vs uncertain,
    function bodies, failure line) applies unchanged to both forms."""
    import ast as _ast
    yield from _orig_calls_in(node)
    for n in _ast.walk(node):
        if (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
                and n.func.id == "call_api" and len(n.args) >= 2
                and isinstance(n.args[0], _ast.Constant) and isinstance(n.args[1], _ast.Constant)
                and isinstance(n.args[0].value, str) and isinstance(n.args[1].value, str)):
            yield (n.args[0].value, n.args[1].value, n.lineno)


A._calls_in = _calls_in


def wrapper_calls(code):
    """Call sites of the LARA wrapper, for the site count only."""
    return [(m.group(1), m.group(2), code[:m.start()].count("\n") + 1)
            for m in WRAPPER.finditer(code)]


def analyse(code, fail_line):
    return A.executed_calls(code, fail_line)


def success_from_report(task_dir):
    f = task_dir / "evaluation" / "report.md"
    if not f.exists():
        return None
    m = re.search(r"Num Failed Tests\s*:\s*(\d+)", f.read_text(errors="replace"))
    t = re.search(r"Num Total\s+Tests\s*:\s*(\d+)", f.read_text(errors="replace"))
    if not m or not t or int(t.group(1)) == 0:
        return None
    return int(int(m.group(1)) == 0)


def wilson(k, n, z=1.96):
    if not n: return (0.0, 0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def process_task(td):
    """Re-run the detector over one task with the adaptations; returns block records
    plus the sequential api_calls alignment used for the `response` level."""
    blocks = A.parse_blocks(td / "logs" / "environment_io.md")
    stream = []
    f = td / "logs" / "api_calls.jsonl"
    if f.exists():
        for line in f.open():
            try:
                d = json.loads(line)
            except Exception:
                continue
            stream.append((route_of(d.get("url"), d.get("method")),
                           (d.get("method") or "get").lower()))
    cur = 0
    recs = []
    for b in blocks:
        oc = A.block_outcome(b["output"])
        code = b["code"] or ""
        if oc["status"] == "failed" and oc["fail_line"] is None:
            conf, unc = [], [(a, n, 0) for a, n in A.APIS_CALL_RE.findall(code)] + \
                             [(a, n, l) for a, n, l in wrapper_calls(code)]
        else:
            conf, unc = analyse(code, oc["fail_line"] if oc["status"] == "failed" else None)
        sites = [(m[0], m[1], 0) for m in A.APIS_CALL_RE.findall(code)] + wrapper_calls(code)
        w_conf = [c for c in conf if A.is_write(c[0], c[1])]
        w_unc = [c for c in unc if A.is_write(c[0], c[1])]
        w_sites = [s for s in sites if A.is_write(s[0], s[1])]
        cls = ("success" if oc["status"] == "success" else
               "fail_after_write" if w_conf else
               "fail_unknown" if w_unc else "fail_before_write")
        # sequential alignment: consume the calls this block is known to have made
        matched = []
        c2 = cur
        for app, api, _ln in conf:
            name = f"{app}.{api}"
            j = next((i for i in range(c2, min(c2 + 400, len(stream)))
                      if stream[i][0] == name), None)
            if j is not None:
                matched.append(name); c2 = j + 1
        cur = c2
        recs.append(dict(block=b["index"], status=oc["status"], cls=cls,
                         fail_line=oc["fail_line"], fail_api=oc.get("fail_api") or "",
                         http_status=oc.get("http_status") or "",
                         n_sites=len(sites), n_write_sites=len(w_sites),
                         n_write_confirmed=len(w_conf), n_calls=len(conf) + len(unc),
                         write_confirmed=";".join(f"{a}.{n}@{l}" for a, n, l in w_conf),
                         aligned=";".join(matched)))
    return recs


def main():
    inv = {r["experiment"]: r for r in csv.DictReader(open("fresh_runs_inventory.csv"))}
    targets = [e for e, v in inv.items()
               if v["era"] in ("modern", "interim") and not v["excluded"]]
    runs = collections.defaultdict(list)
    for r in csv.DictReader(open("runs.csv")):
        if r["experiment"] in targets:
            runs[r["experiment"]].append(r)

    brows, frows = [], []
    for exp in sorted(targets):
        for r in runs[exp]:
            td = pathlib.Path(r["path"])
            try:
                recs = process_task(td)
            except Exception as e:
                continue
            succ = r["task_success"]
            if succ == "0":
                s2 = success_from_report(td)
                if s2 is not None:
                    succ = str(s2)
            for rec in recs:
                row = dict(era=inv[exp]["era"], experiment=exp, agent=r["agent"],
                           model=r["model"], dataset=r["dataset"], task_id=r["task_id"],
                           task_success=succ, path=str(td), **rec)
                brows.append(row)
                if rec["cls"] == "fail_after_write":
                    wa = [w.split("@")[0] for w in rec["write_confirmed"].split(";") if w]
                    al = set(rec["aligned"].split(";"))
                    lvl = "response" if any(w in al for w in wa) else "assumed"
                    why = ("write matched to an entry in api_calls.jsonl "
                           "by sequential matching" if lvl == "response"
                           else "confirmation only by code and traceback")
                    frows.append(dict(row, confirmation=lvl, confirmation_basis=why))

    with open("fresh_blocks.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(brows[0])); w.writeheader(); w.writerows(brows)
    with open("fresh_fail_after_write.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(frows[0])); w.writeheader(); w.writerows(frows)

    print(f"blocks rechecked: {len(brows)} | fail_after_write: {len(frows)}\n")
    print("| experiment | model | boundary | blocks | failed with write | fail_after_write | share [95% CI] | response |")
    print("|---|---|---|--:|--:|--:|---|--:|")
    for exp in sorted(targets):
        g = [b for b in brows if b["experiment"] == exp]
        if not g: continue
        med = statistics.median([b["n_calls"] for b in g]) if g else 0
        bnd = "observed_call" if med <= 1 else "composite_block"
        nfw = sum(1 for b in g if b["cls"].startswith("fail") and b["n_write_sites"] > 0)
        k = sum(1 for b in g if b["cls"] == "fail_after_write")
        resp = sum(1 for b in frows if b["experiment"] == exp and b["confirmation"] == "response")
        p, lo, hi = wilson(k, nfw)
        print(f"| {exp} | {g[0]['model']} | {bnd} | {len(g)} | {nfw} | {k} | "
              f"{100*p:.1f} % [{100*lo:.1f}, {100*hi:.1f}] | {resp} |")


if __name__ == "__main__":
    main()
