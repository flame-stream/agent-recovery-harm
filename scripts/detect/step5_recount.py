#!/usr/bin/env python3
"""Step 5: recount the corpus under three rules + visibility measure (Q5)."""
import csv, json, collections, pathlib, sys, math
import idempotency
import appworld_audit as A

TBL = idempotency.load()
I = lambda r, k: int(r[k]) if r.get(k) not in (None, "") else 0
def pct(a, b): return f"{100.0*a/b:.1f}% ({a}/{b})" if b else "— (0/0)"
CART = {"add_product_to_cart", "clear_cart", "add_gift_wrapping_to_product",
        "apply_promo_code_to_cart", "remove_promo_code_from_cart", "delete_product_from_cart",
        "move_product_from_cart_to_wish_list", "move_product_from_wish_list_to_cart",
        "remove_gift_wrapping_from_product", "update_product_quantity_in_cart"}


def family(api):
    if not api: return "none"
    app, _, n = api.partition(".")
    if app == "amazon": return "amazon_cart" if n in CART else "amazon_other"
    if app == "gmail": return "gmail"
    if app == "file_system": return "filesystem"
    if app in ("venmo", "splitwise"): return "payments"
    if app == "spotify": return "spotify"
    return "other"


def rule_a(r):                       # old: repeat executed and the API is a POST
    return I(r, "harmful_candidate")


def rule_b(r, cart_clear_first):     # refined by API semantics
    if not I(r, "repeat_confirmed_write") or not I(r, "new_effect"):
        return 0
    cls = (TBL.get(r["repeated_api"]) or {}).get("cls", "unknown")
    if cls not in ("duplicating", "accumulating"):
        return 0
    # replay showed that add_product_to_cart(clear_cart_first=True) is net-idempotent
    if r["repeated_api"] == "amazon.add_product_to_cart" and r["path"] + "#" + r["repeat_block"] in cart_clear_first:
        return 0
    return 1


def main():
    EP = list(csv.DictReader(open("fail_after_write.csv")))
    # which cart repeats passed clear_cart_first=True (read from the recovery block's code)
    cart_clear = set()
    for r in EP:
        if r["repeated_api"] != "amazon.add_product_to_cart" or not r["repeat_block"]:
            continue
        bs = {b["index"]: b for b in A.parse_blocks(pathlib.Path(r["path"]) / "logs" / "environment_io.md")}
        b = bs.get(int(r["repeat_block"]))
        if b and "clear_cart_first" in b["code"] and "True" in b["code"]:
            cart_clear.add(r["path"] + "#" + r["repeat_block"])
    for r in EP:
        r["_A"] = rule_a(r)
        r["_B"] = rule_b(r, cart_clear)
        r["_fam"] = family((r["confirmed_writes"] or "").split(";")[0])
        r["_link"] = (r["path"], r["block"], r["repeated_api"])
    n = len(EP)
    print(f"episodes: {n}; unique links (run, failed block, repeated API): "
          f"{len({r['_link'] for r in EP})}\n")
    print("## Rules\n")
    print("| rule | unit | harmful repeats | share of 1897 episodes |")
    print("|---|---|--:|--:|")
    a = sum(r["_A"] for r in EP); b = sum(r["_B"] for r in EP)
    linkA = {r["_link"] for r in EP if r["_A"]}; linkB = {r["_link"] for r in EP if r["_B"]}
    print(f"| A — old («POST executed») | episode | {a} | {pct(a, n)} |")
    print(f"| B — API semantics (idempotency) | episode | {b} | {pct(b, n)} |")
    print(f"| C — unique links, rule B | link | {len(linkB)} | — |")
    print(f"| (for reference) unique links, rule A | link | {len(linkA)} | — |")
    print()
    print("## Without amazon.add_product_to_cart\n")
    noc = [r for r in EP if r["repeated_api"] != "amazon.add_product_to_cart"]
    a2 = sum(r["_A"] for r in noc); b2 = sum(r["_B"] for r in noc)
    print(f"episodes: {len(noc)}; rule A: {pct(a2, len(noc))}; rule B: {pct(b2, len(noc))}; "
          f"unique links by B: {len({r['_link'] for r in noc if r['_B']})}")
    print()
    print("## By family\n")
    print("| family | episodes | rule A | rule B | links by B |")
    print("|---|--:|--:|--:|--:|")
    by = collections.defaultdict(list)
    for r in EP: by[r["_fam"]].append(r)
    for k, g in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"| {k} | {len(g)} | {pct(sum(x['_A'] for x in g), len(g))} | "
              f"{pct(sum(x['_B'] for x in g), len(g))} | {len({x['_link'] for x in g if x['_B']})} |")
    print()
    print("## Idempotency classes among repeats\n")
    c = collections.Counter((TBL.get(r["repeated_api"]) or {}).get("cls", "n/a")
                            for r in EP if r["repeated_api"])
    tot = sum(c.values())
    print("| class | repeats | share |")
    print("|---|--:|--:|")
    for k, v in c.most_common(): print(f"| {k} | {v} | {pct(v, tot)} |")
    print()
    # concentration for rule B
    per = collections.Counter(r["path"] for r in EP if r["_B"])
    vals = sorted(per.values(), reverse=True); tot2 = sum(vals)
    acc = n50 = n80 = 0
    for i, v in enumerate(vals, 1):
        acc += v
        if not n50 and acc >= 0.5*tot2: n50 = i
        if not n80 and acc >= 0.8*tot2: n80 = i
    print(f"Rule B: {tot2} harmful repeats in {len(vals)} runs; "
          f"50 % give {n50} runs, 80 % — {n80}; median {statistics.median(vals) if vals else 0:.0f}, max {max(vals) if vals else 0}.")
    with open("corpus_rules.csv", "w", newline="") as f:
        cols = ["path", "task_id", "agent", "model", "block", "repeat_block", "repeated_api",
                "_fam", "_A", "_B"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(EP)


if __name__ == "__main__":
    import statistics
    main()
