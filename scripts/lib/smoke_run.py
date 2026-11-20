#!/usr/bin/env python3
"""Smoke runner: continue a historical AppWorld episode with the legacy ReAct Code Agent
driven by gpt-oss-20b in LM Studio. Logs every raw request/response."""
import csv, json, re, sys, time, pathlib, shutil, argparse
sys.path.insert(0, "."); sys.path.insert(0, "..")
import urllib.request


def now():
    """freezegun (used by AppWorld to pin the task datetime) patches time.time,
    time.monotonic and time.perf_counter; CLOCK_MONOTONIC_RAW is untouched."""
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
import replay_lib as R
import intercept_lib as IL
from run_replay import load_blocks
from smoke_prompt import build, GEN, trim, to_messages, history_text, fill_instructions

BASE_URL = "http://<local-server>/v1"
MODEL = "gpt-oss-20b"
LOGDIR = pathlib.Path("../smoke_logs"); LOGDIR.mkdir(exist_ok=True)
CODE_RE = re.compile(r'```python\n(.*?)(?:\n```|\Z)', re.S)
HARMONY_MSG = re.compile(r'<\|message\|>')
HARMONY_ANY = re.compile(r'<\|[a-z_]+\|>')


def normalise_harmony(content):
    """gpt-oss routes the code into the harmony `commentary to=python` channel, and LM
    Studio 1.1.3 passes that channel through into `content` verbatim (it only parses the
    `analysis` channel into `reasoning`). Take the payload after the LAST <|message|>.
    Returns (text, was_harmony)."""
    if content is None:
        return None, False
    if not HARMONY_MSG.search(content):
        return content, False
    tail = HARMONY_MSG.split(content)[-1]
    tail = HARMONY_ANY.split(tail)[0]
    return tail, True


def extract_code(content):
    """Returns (code, n_fenced_blocks, was_harmony). The original config stops generation
    at '```\n', so the closing fence is usually absent."""
    text, harmony = normalise_harmony(content)
    if text is None:
        return None, 0, harmony
    blocks = CODE_RE.findall(text)
    if blocks:
        return blocks[0].strip(), len(blocks), harmony
    if harmony:
        code = re.sub(r'^\s*Code:\s*', "", text).strip()
        code = re.sub(r'^```(?:python)?\n?', "", code).strip()
        return (code or None), 0, harmony
    return None, 0, harmony


def chat(messages, tag, seed=GEN["seed"], temperature=GEN["temperature"],
         max_tokens=GEN["max_tokens"], reasoning_effort=None, stop=GEN["stop"]):
    body = dict(model=MODEL, messages=messages, temperature=temperature, seed=seed,
                max_tokens=max_tokens, stop=stop)
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE_URL + "/chat/completions", data=data,
                                 headers={"Content-Type": "application/json"})
    # AppWorld freezes the system clock (freezegun) for the task datetime, so
    # time.time() does not advance while a world is open. Use perf_counter.
    t0 = now()
    with urllib.request.urlopen(req, timeout=1800) as r:
        resp = json.loads(r.read().decode())
    dt = now() - t0
    json.dump(dict(request=body, response=resp, seconds=dt),
              open(LOGDIR / f"{tag}.json", "w"), indent=1)
    return resp, dt




def run_episode(ep, arm="traceback", tag="t", reasoning_effort=None, max_steps=None,
                seed=GEN["seed"], max_tokens=GEN["max_tokens"], stop=GEN["stop"]):
    from appworld import AppWorld
    blocks = load_blocks(pathlib.Path("..") / ep["path"])
    pos = {b["num"]: i for i, b in enumerate(blocks)}
    fi = pos[int(ep["fail_block"])]
    limit = max_steps if max_steps is not None else (len(blocks) - fi - 1)
    exp = f"smoke_{tag}"
    d = pathlib.Path("experiments/outputs") / exp
    if d.exists():
        shutil.rmtree(d)
    cap = IL.patch_capture()
    world = AppWorld(task_id=ep["task_id"], experiment_name=exp,
                     max_interactions=len(blocks) + limit + 10,
                     max_api_calls_per_interaction=1000,
                     raise_on_failure=True, timeout_seconds=100)
    itc = IL.Interceptor(world, None, f"../smoke_logs/snap_{tag}")
    itc.enable()
    hist = []
    for i in range(0, fi + 1):
        itc.block = f"hist{i}"
        out = world.execute(blocks[i]["code"])
        hist.append(dict(code=blocks[i]["code"], output=out))
    arm_response = hist[-1]["output"]        # arm 1: traceback, exactly as the env gives
    hist[-1]["output"] = arm_response
    instr, spec = fill_instructions(ep["task_id"])
    steps, done, parse_fail = [], False, 0
    for step in range(limit):
        full = instr + history_text(hist, len(hist) - 1)
        msgs = to_messages(trim(full))
        if reasoning_effort:
            msgs = [{"role": "system", "content": f"Reasoning: {reasoning_effort}"}] + msgs
        resp, dt = chat(msgs, f"{tag}_step{step:02d}", seed=seed, max_tokens=max_tokens,
                        stop=stop)
        m = resp["choices"][0]["message"]
        code, nblocks, harmony = extract_code(m.get("content"))
        usage = resp.get("usage", {})
        rec = dict(step=step, seconds=round(dt, 1), prompt_tokens=usage.get("prompt_tokens"),
                   completion_tokens=usage.get("completion_tokens"),
                   reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                   n_code_blocks=nblocks, harmony_channel=int(harmony),
                   finish=resp["choices"][0].get("finish_reason"),
                   reasoning_chars=len(m.get("reasoning") or ""),
                   content_chars=len(m.get("content") or ""),
                   reasoning_leaked_into_content=int(bool(
                       m.get("reasoning") and m.get("reasoning")[:60] in (m.get("content") or ""))),
                   code=code)
        if code is None:
            parse_fail += 1
            rec["env_output"] = None
            steps.append(rec)
            break
        itc.block = f"cont{step}"
        out = world.execute(code)
        rec["env_output"] = out[:400]
        steps.append(rec)
        hist.append(dict(code=code, output=out))
        if "complete_task" in code:
            done = True
            break
    itc.disable()
    try:
        world.close()
    except Exception:
        pass
    return dict(ep_id=ep["ep_id"], task_id=ep["task_id"], family=ep["family"], arm=arm,
                reasoning_effort=reasoning_effort, seed=seed, limit=limit,
                max_tokens=max_tokens, stop=stop,
                steps=steps, completed=done, parse_failures=parse_fail,
                codes=[s["code"] for s in steps if s["code"] is not None],
                total_seconds=round(sum(s["seconds"] for s in steps), 1),
                last_prompt_tokens=steps[-1]["prompt_tokens"] if steps else None,
                write_calls=[r for r in itc.records if r["block"].startswith("cont")])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", default="")
    ap.add_argument("--tag", default="c2")
    ap.add_argument("--effort", default="")
    ap.add_argument("--seed", type=int, default=GEN["seed"])
    ap.add_argument("--max-tokens", type=int, default=GEN["max_tokens"])
    ap.add_argument("--no-stop", action="store_true",
                    help="drop the original stop sequence ```\\n: with gpt-oss it can fire "
                         "inside the reasoning channel and leave content empty")
    a = ap.parse_args()
    E = {r["ep_id"]: r for r in csv.DictReader(open("../b_episodes.csv"))}
    ids = a.episodes.split(",")
    out = []
    for eid in ids:
        ep = E[eid]
        t0 = now()
        r = run_episode(ep, tag=f"{a.tag}_ep{eid}", reasoning_effort=(a.effort or None),
                        seed=a.seed, max_tokens=a.max_tokens,
                        stop=(None if a.no_stop else GEN["stop"]))
        r["wall_seconds"] = round(now() - t0, 1)
        out.append(r)
        print(f"ep {eid} {ep['family']:10s} steps={len(r['steps'])} completed={r['completed']} "
              f"parse_fail={r['parse_failures']} llm_s={r['total_seconds']} "
              f"wall_s={r['wall_seconds']} last_prompt_tok={r['last_prompt_tokens']}", flush=True)
    json.dump(out, open(f"../smoke_{a.tag}.json", "w"), indent=1, default=str)
    print("wrote", f"../smoke_{a.tag}.json")
