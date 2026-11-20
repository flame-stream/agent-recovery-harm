#!/usr/bin/env python3
"""Smoke test of the condition-E guard on a live world (no model)."""
import os, sys, pathlib, json
PROJ = pathlib.Path(os.environ["PROJ"]); STAND = pathlib.Path(os.environ["STAND"])
sys.path.insert(0, str(PROJ)); os.chdir(PROJ)
import effects_runtime_e as EE
os.chdir(STAND)
from appworld import AppWorld
w = AppWorld(task_id="b6d1f70_2", experiment_name="e_guard_test")
try:
    print(w.execute(EE.preamble())[-200:] or "preamble ok")
    print(w.execute("print(len(_ORIG_WRITES), 'write apis guarded')"))
    tok = "pw = [a for a in apis.supervisor.show_account_passwords() if a['account_name']=='amazon'][0]['password']\n" \
          "prof = apis.supervisor.show_profile()\n" \
          "t = apis.amazon.login(username=prof['email'], password=pw)['access_token']\nprint('login ok')"
    print(w.execute(tok))
    print("DIRECT:", w.execute("apis.amazon.add_product_to_cart(access_token=t, product_id=1, quantity=1)")[-160:])
    print("ITEM  :", w.execute("apis['amazon']['add_product_to_cart'](access_token=t, product_id=1, quantity=1)")[-160:])
    print("ROUTED:", w.execute("r = effects.call('op-1', 'amazon.add_product_to_cart', {'access_token': t, 'product_id': 1, 'quantity': 1}); print(r)")[-160:])
    print("REPEAT:", w.execute("print(effects.call('op-1', 'amazon.add_product_to_cart', {'access_token': t, 'product_id': 1, 'quantity': 1}))")[-160:])
    print("READ  :", w.execute("print(len(apis.amazon.show_cart(access_token=t)['cart_items']))")[-80:])
    print("JOURNAL:", w.execute("print(effects.dump())")[-600:])
finally:
    w.close()
