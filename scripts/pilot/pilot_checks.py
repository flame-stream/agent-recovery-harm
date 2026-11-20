#!/usr/bin/env python3
"""Section 6 technical checks that need no LLM: 3, 4 and 5."""
import json, os, pathlib, re, sys

PROJ = pathlib.Path(os.environ["PROJ"]).resolve()
STAND = pathlib.Path(os.environ["STAND"]).resolve()
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)
import instrument as I
import effects_runtime as E
FREEZE = I.verify_freeze()
os.chdir(STAND)
from appworld import AppWorld

TASK = os.environ.get("TASK", "024c982_1")
SETUP = """
_ps = {x['account_name']: x['password'] for x in apis.supervisor.show_account_passwords()}
_me = apis.supervisor.show_profile()['email']
_tok = apis.amazon.login(username=_me, password=_ps['amazon'])['access_token']
"""


def mk(tag, mode):
    w = AppWorld(task_id=TASK, experiment_name=f"chk_{tag}")
    rec = I.Recorder(w, ["amazon"], STAND / "chk_work" / tag, watch=lambda a, n: True)
    rec.enable()
    w.execute(SETUP)
    w.execute(E.preamble(mode))
    return w, rec


def pid_of(w):
    out = w.execute("print(apis.amazon.search_products(query='board game', page_limit=3))")
    return int(re.search(r'"product_id":\s*(\d+)', out).group(1))


def journal(w):
    return json.loads(w.execute("print(effects.dump())").strip().splitlines()[-1])


def check3(res):
    """A completed operation returns the stored result and does not call again."""
    w, rec = mk("c3", "enforce")
    pid = pid_of(w)
    A, mA = rec.snap("A")
    w.execute(f"print(effects.call('op1','amazon.add_product_to_cart',"
              f"dict(access_token=_tok, product_id={pid}, quantity=1)))")
    B, mB = rec.snap("B")
    w.execute(f"print(effects.call('op1','amazon.add_product_to_cart',"
              f"dict(access_token=_tok, product_id={pid}, quantity=1)))")
    C, mC = rec.snap("C")
    j = journal(w)
    res.update(first_changed=bool(I.diff(A, B, mA, mB)),
               second_changed=bool(I.diff(B, C, mB, mC)),
               decisions=[e["decision"] for e in j],
               passed=(bool(I.diff(A, B, mA, mB)) and not I.diff(B, C, mB, mC)
                       and [e["decision"] for e in j][-1] == "returned_stored"))
    w.close()


def check4(res):
    """Two different ids let a legitimate repeat through."""
    w, rec = mk("c4", "enforce")
    pid = pid_of(w)
    A, mA = rec.snap("A")
    for op in ("opA", "opB"):
        w.execute(f"print(effects.call('{op}','amazon.add_product_to_cart',"
                  f"dict(access_token=_tok, product_id={pid}, quantity=1)))")
    C, mC = rec.snap("C")
    qa, qc = I.cart_map(A.get("amazon.cart_entries", [])), I.cart_map(C.get("amazon.cart_entries", []))
    k = next((x for x in qc if x[1] == pid), None)
    j = journal(w)
    res.update(decisions=[e["decision"] for e in j],
               qty_before=(qa.get(k) or (0,))[0], qty_after=(qc.get(k) or (0,))[0],
               passed=(all(e["decision"] == "executed" for e in j)
                       and (qc.get(k) or (0,))[0] == ((qa.get(k) or (0,))[0] or 0) + 2))
    w.close()


def check5(res):
    """Mechanism test on correct labels: repeat suppressed, legitimate executed,
    conflict on changed arguments — all under enforcement."""
    w, rec = mk("c5", "enforce")
    out = w.execute("print([p['product_id'] for p in "
                    "apis.amazon.search_products(query='board game', page_limit=3)])")
    ids = [int(x) for x in re.findall(r"\d+", out.splitlines()[-1])][:2]
    p1, p2 = ids[0], ids[1]
    A, mA = rec.snap("A")
    # pre-labelled "original block": two distinct operations
    w.execute(f"""
effects.call('add-{p1}','amazon.add_product_to_cart', dict(access_token=_tok, product_id={p1}, quantity=1))
effects.call('add-{p2}','amazon.add_product_to_cart', dict(access_token=_tok, product_id={p2}, quantity=1))
""")
    B, mB = rec.snap("B")
    # pre-labelled "recovery": repeats the first, adds a third legitimate op, and then
    # reuses a completed id with different arguments
    w.execute(f"""
effects.call('add-{p1}','amazon.add_product_to_cart', dict(access_token=_tok, product_id={p1}, quantity=1))
effects.call('add-extra','amazon.add_product_to_cart', dict(access_token=_tok, product_id={p1}, quantity=1))
try:
    effects.call('add-{p2}','amazon.add_product_to_cart', dict(access_token=_tok, product_id={p2}, quantity=5))
except Exception as e:
    print('CONFLICT', type(e).__name__)
""")
    C, mC = rec.snap("C")
    j = journal(w)
    qb, qc = I.cart_map(B.get("amazon.cart_entries", [])), I.cart_map(C.get("amazon.cart_entries", []))
    k1 = next((x for x in qc if x[1] == p1), None)
    k2 = next((x for x in qc if x[1] == p2), None)
    dec = [(e["op"], e["decision"]) for e in j]
    res.update(decisions=dec,
               repeat_suppressed=(dec[2][1] == "returned_stored"),
               legit_executed=(dec[3][1] == "executed"),
               conflict_raised=(dec[4][1] == "operation_conflict"),
               qty_p1=((qb.get(k1) or (0,))[0], (qc.get(k1) or (0,))[0]),
               qty_p2=((qb.get(k2) or (0,))[0], (qc.get(k2) or (0,))[0]))
    res["passed"] = (res["repeat_suppressed"] and res["legit_executed"]
                     and res["conflict_raised"]
                     and res["qty_p1"][1] == res["qty_p1"][0] + 1   # only the new op added
                     and res["qty_p2"][1] == res["qty_p2"][0])      # conflict changed nothing
    w.close()


def main():
    out = {"freeze": FREEZE}
    for name, fn in (("3_stored_result", check3), ("4_two_ids", check4),
                     ("5_mechanism", check5)):
        r = {}
        try:
            fn(r)
        except Exception as e:
            import traceback
            r.update(passed=False, error=f"{type(e).__name__}: {e}"[:200],
                     trace=traceback.format_exc()[-300:])
        out[name] = r
        print(f"[{name}] {'PASSED' if r.get('passed') else 'FAILED'} "
              f"{json.dumps({k: v for k, v in r.items() if k not in ('trace',)}, ensure_ascii=False)[:220]}",
              flush=True)
    json.dump(out, open(PROJ / f"pilot_checks_{os.environ.get('VER','x')}.json", "w"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
