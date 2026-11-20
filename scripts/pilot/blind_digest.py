#!/usr/bin/env python3
"""Step 1: blind digest for outcome labelling.

Hidden: condition, episode id, block, arm, the agent's code (it would reveal effects.call),
the wrapper journal. Shown: task text, the continuation's write calls in order (args
without tokens, error, per-call row delta), net B->C and net A->C (substance, row ids
dropped), and the user's rows of each touched table in A as context.

Snapshot rule from the damage close-out: a call whose delta makes >=3 tables appear or
vanish whole, or moves >=50 rows of one table, is marked unreliable and its delta is not
shown; such items are judged from the net diff (and may be undecidable).

Usage: python blind_digest.py <name> <seed> <glob of result files>  -> <name>.json + <name>_map.json
The map file must not be opened before the labels are saved.
"""
import collections, csv, glob, json, pathlib, random, sys
sys.path.insert(0, ".")
import instrument as I
import appworld_audit as A

NOISE_TABLES = {"amazon.products"}          # inventory counters move with every order
MAX_ROWS = 8


def short(row, n=230):
    s = I.substance(row)
    try:
        d = json.loads(s)
        d = {k: v for k, v in d.items() if k not in ("password", "password_reset_code")}
        s = json.dumps(d, ensure_ascii=False, sort_keys=True)
    except Exception:
        pass
    return s if len(s) <= n else s[:n] + "…"


_INIT = {}


def initial_max(dv, task_id, table):
    """Max row id of `table` at task start: base DB max plus the task's own INSERTs."""
    k = (dv, task_id, table)
    if k not in _INIT:
        import sqlite3
        root = pathlib.Path("replay_root" if dv == "0.1.0" else "stand020") / "data"
        app, _, name = table.partition(".")
        try:
            con = sqlite3.connect(root / "base_dbs" / f"{app}.db")
            m = con.execute(f"select max(id) from {name}").fetchone()[0] or 0
            con.close()
        except Exception:
            m = None
        if m is not None:
            jl = root / "tasks" / task_id / "dbs" / f"{app}.jsonl"
            if jl.exists():
                for line in jl.read_text().splitlines():
                    if line.startswith(f'["INSERT INTO {name} '):
                        m += 1
        _INIT[k] = m
    return _INIT[k]


def origin_tags(X, table, dv, task_id):
    """substance -> 'original' / 'created in the episode' by row id against the task start."""
    m = initial_max(dv, task_id, table)
    tags = {}
    for r in X.get(table, []):
        i = I.row_id(r)
        if m is None or i is None:
            continue
        tags.setdefault(I.substance(r), "original" if i <= m else "created in the episode")
    return tags


def net(X, Y):
    out = {}
    for t in sorted(set(X) | set(Y)):
        cx = collections.Counter(I.substance(r) for r in X.get(t, []))
        cy = collections.Counter(I.substance(r) for r in Y.get(t, []))
        add, rem = list((cy - cx).elements()), list((cx - cy).elements())
        if add or rem:
            out[t] = (add, rem)
    return out


def fmt_net(d, X=None, dv=None, task_id=None):
    res = {}
    for t, (add, rem) in d.items():
        if t in NOISE_TABLES:
            res[t] = f"(service counters: +{len(add)} / -{len(rem)} rows)"
            continue
        tags = origin_tags(X, t, dv, task_id) if X is not None else {}
        res[t] = dict(added=[short(x) for x in add[:MAX_ROWS]], n_added=len(add),
                      removed=[f"[{tags.get(x, '?')}] " + short(x) for x in rem[:MAX_ROWS]],
                      n_removed=len(rem))
    return res


def user_ids(*nets):
    ids = collections.Counter()
    for d in nets:
        for t, (add, rem) in d.items():
            for r in add + rem:
                try:
                    u = json.loads(r).get("user_id")
                except Exception:
                    u = None
                if u is not None:
                    ids[u] += 1
    return {u for u, _ in ids.most_common(1)}


def context(Astate, tables, uids, dv, task_id):
    ctx = {}
    for t in tables:
        if t in NOISE_TABLES:
            continue
        rows = []
        for r in Astate.get(t, []):
            try:
                d = json.loads(r)
            except Exception:
                continue
            if d.get("user_id") in uids:
                rows.append((d.get("id") or 0, r))
        rows.sort()
        m = initial_max(dv, task_id, t)
        made = [r for i, r in rows if m is not None and i > m]
        ctx[t] = dict(n_user_rows_in_A=len(rows),
                      last_rows=[short(r) for _, r in rows[-MAX_ROWS:]],
                      created_in_episode_before_A=[short(r) for r in made[-MAX_ROWS:]],
                      n_created_in_episode_before_A=len(made) if m is not None else None)
    return ctx


def unreliable(delta):
    # instrument.diff marks a table `unknown` when it was not read in one of the two
    # snapshots -- the empty-snapshot failure that produced whole-table phantoms
    whole = sum(1 for v in delta.values()
                if isinstance(v, dict) and v.get("status") == "unknown")
    big = any(isinstance(v, dict) and
              max(v.get("n_added", len(v.get("added", []))),
                  v.get("n_removed", len(v.get("removed", [])))) >= 50
              for v in delta.values())
    return whole >= 3 or big


def call_view(e):
    d = e.get("delta") or {}
    v = dict(api=e["api"], args={k: v for k, v in (e.get("args") or {}).items()
                                 if k not in ("access_token", "password")},
             error=(e.get("error") or "")[:160] or None)
    if unreliable(d):
        v["delta"] = "SNAPSHOT UNRELIABLE: delta not shown"
    else:
        dd = {}
        for t, x in d.items():
            if t in NOISE_TABLES or not isinstance(x, dict):
                continue
            a = [short(r, 160) for r in x.get("added", [])][:4]
            r_ = [short(r, 160) for r in x.get("removed", [])][:4]
            if a or r_:
                dd[t] = dict(added=a, removed=r_)
        v["delta"] = dd
    return v


def compact(views, keep=40):
    """Calls that changed nothing are summarised by (api, error); calls with a row delta or
    an unreliable snapshot are kept in order (first `keep`), so the history stays readable
    for continuations that loop on a failing write hundreds of times."""
    kept, idle = [], collections.Counter()
    for i, v in enumerate(views, 1):
        if v["delta"] == {} and v["error"]:
            idle[(v["api"], v["error"][:90])] += 1
        else:
            if v["delta"] == {}:
                v = dict(v, delta="successful, no visible delta (app outside the snapshot or no change)")
            kept.append(dict(n=i, **v))
    out = dict(n_write_calls=len(views), with_effect=kept[:keep],
               with_effect_not_shown=max(0, len(kept) - keep),
               no_effect=[dict(api=a, result=e, times=c) for (a, e), c in idle.most_common(12)])
    return out


def main():
    name, seed, pats = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    eps = {(r["task_id"], r["block"]): r for r in csv.DictReader(open("episodes.csv"))}
    items = []
    for pat in pats:
        for f in sorted(glob.glob(pat)):
            base = pathlib.Path(f).parent
            out = base if base.name == "pilot_E" else pathlib.Path("pilot_out")
            for r in json.load(open(f)):
                if not r.get("usable"):
                    continue
                key = f"{r['condition']}__{r['task_id']}__{r['block']}"
                snap = json.load(open(out / f"snap_{key}.json"))
                calls = json.load(open(out / f"calls_{key}.json"))
                Astate, B, C = snap["A"], snap["B"], snap["C"]
                nBC, nAC = net(B, C), net(Astate, C)
                uids = user_ids(nAC, nBC)
                dv = eps[(r["task_id"], r["block"])]["data_version"]
                writes = compact([call_view(e) for e in calls
                                  if A.is_write(*e["api"].split(".", 1))])
                items.append(dict(
                    key=key,
                    task=eps[(r["task_id"], r["block"])]["instruction"],
                    continuation_write_calls=writes,
                    net_B_to_C=fmt_net(nBC, B, dv, r["task_id"]),
                    net_A_to_C=fmt_net(nAC, Astate, dv, r["task_id"]),
                    user_rows_in_A=context(Astate, sorted(set(nAC) | set(nBC)), uids,
                                           dv, r["task_id"])))
    rnd = random.Random(seed)
    rnd.shuffle(items)
    blind, mp = [], []
    for i, it in enumerate(items, 1):
        mp.append(dict(slot=i, key=it.pop("key")))
        blind.append(dict(slot=i, **it))
    json.dump(blind, open(f"reports/pilot_closeout/{name}.json", "w"), ensure_ascii=False, indent=1)
    json.dump(mp, open(f"reports/pilot_closeout/{name}_map.json", "w"), ensure_ascii=False)
    print(f"{name}.json: {len(blind)} records, seed={seed}; map -> {name}_map.json (do not open)")


if __name__ == "__main__":
    main()
