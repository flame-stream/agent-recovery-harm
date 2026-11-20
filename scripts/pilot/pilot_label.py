#!/usr/bin/env python3
"""Section 4: the model labels the failed block with operation ids, before execution.

The model sees the task, the history up to the failed block and the block itself. It
does NOT see the traceback and does not see how the run actually recovered. It must
wrap every write in effects.call(operation_id, api, arguments), keeping the order,
the arguments and the logic.
"""
import json, os, pathlib, re, sys, time

PROJ = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ / "replay_root"))
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)
import appworld_audit as A
from smoke_run import normalise_harmony, extract_code, chat, MODEL
import effects_runtime as E

GEN = dict(temperature=0, seed=123, max_tokens=3072, stop=None)
EFFORT = "medium"
WRITE = set(open(PROJ / "write_apis.txt").read().split())

INSTRUCT = """You are labelling a code block with labels of logical operations.

Label rules:
- every WRITE (a call that changes state) must go through
  effects.call(operation_id, "<app>.<api>", dict(<the same arguments>))
- operation_id — a string denoting ONE logical operation of the task.
  The same operation keeps its id when the code is rewritten.
  A new legitimate action gets a NEW id, even if the arguments match.
- in a loop, each required action gets its own id (for example f"reply-{email_id}").
- do NOT wrap reads (show_*, search_*, login, etc.).
- keep the order of calls, the arguments and the program logic unchanged.
- return only the code in a single block ```python ... ```

Example:
    apis.amazon.add_product_to_cart(access_token=t, product_id=5, quantity=1)
becomes
    effects.call("add-5", "amazon.add_product_to_cart",
                 dict(access_token=t, product_id=5, quantity=1))
"""


def block_and_context(ep):
    td = pathlib.Path(ep["path"])
    blocks = A.parse_blocks(td / "logs" / "environment_io.md")
    pos = {b["index"]: i for i, b in enumerate(blocks)}
    i = pos[int(ep["block"])]
    hist = []
    for b in blocks[max(0, i - 4):i]:
        hist.append(f"CODE:\n{(b['code'] or '')[:700]}\nRESPONSE:\n{(b['output'] or '')[:300]}")
    return blocks, i, "\n---\n".join(hist)


def main():
    eps = list(__import__("csv").DictReader(open(PROJ / "episodes.csv")))
    out = {}
    p = PROJ / "labelled_blocks.json"
    if p.exists():
        out = json.load(open(p))
    for ep in eps:
        key = ep["episode_id"]
        if key in out:
            continue
        blocks, i, hist = block_and_context(ep)
        code = blocks[i]["code"]
        msgs = [{"role": "system", "content": f"Reasoning: {EFFORT}"},
                {"role": "user", "content":
                 f"{INSTRUCT}\nTASK: {ep['instruction']}\n\nPREVIOUS STEPS:\n{hist}\n\n"
                 f"BLOCK TO LABEL:\n```python\n{code}\n```"}]
        t0 = time.time()
        r, _dt = chat(msgs, "label_" + re.sub(r"[^A-Za-z0-9_.-]", "_", key)[-40:],
                      seed=GEN["seed"], temperature=GEN["temperature"],
                      max_tokens=GEN["max_tokens"], stop=GEN["stop"])
        m = r["choices"][0]["message"]
        got, nfence, harmony = extract_code(m.get("content"))
        u = r.get("usage", {})
        out[key] = dict(episode_id=key, original=code, labelled=got or "",
                        n_fenced=nfence, harmony=harmony,
                        completion_tokens=u.get("completion_tokens"),
                        finish=r["choices"][0].get("finish_reason"),
                        seconds=round(time.time() - t0, 1))
        json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
        print(f"[{len(out)}/{len(eps)}] {ep['task_id']}#{ep['block']} "
              f"code={'yes' if got else 'NO'} tokens={u.get('completion_tokens')} "
              f"finish={r['choices'][0].get('finish_reason')}", flush=True)


if __name__ == "__main__":
    main()
