#!/usr/bin/env python3
"""Rebuild the legacy ReAct Code Agent prompt exactly as the original config does.

Config (experiments/configs/legacy_react_code_agent/.../test_normal.jsonnet):
  prompt_file      react_code_agent/_legacy_instructions.txt
  max_prompt_length 50000   -- CHARACTERS, trimmed from the left (appworld_prompted_lm.py:24-40)
  add_roles        true     -- USER:/ASSISTANT: markers become chat messages
  generator        max_tokens 400, seed 123, stop ["```\n"], temperature 0
"""
import json, pathlib, re

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE if (_HERE / "harness").exists() else _HERE.parent
INSTR = (_ROOT / "harness/react_legacy_instructions.txt").read_text()
import os as _os
_DATA = pathlib.Path(_os.environ.get("APPWORLD_DATA", _ROOT / "replay_root" / "data"))
MAX_PROMPT_CHARS = 50000
GEN = dict(max_tokens=400, seed=123, stop=["```\n"], temperature=0)


def fill_instructions(task_id):
    spec = json.load(open(_DATA / "tasks" / task_id / "specs.json"))
    sup = spec["supervisor"]
    s = INSTR
    for k in ("first_name", "last_name", "email", "phone_number"):
        s = s.replace("{{ main_user.%s }}" % k, sup[k])
    return s.replace("{{ input_str }}", spec["instruction"]), spec


def history_text(blocks, upto_idx, last_output_override=None):
    """ASSISTANT/USER turns for blocks[0..upto_idx] as the agent saw them."""
    out = []
    for i, b in enumerate(blocks[: upto_idx + 1]):
        out.append("\nASSISTANT:\nCode:\n```python\n" + b["code"] + "\n```\n")
        o = b["output"]
        if i == upto_idx and last_output_override is not None:
            o = last_output_override
        out.append("\nUSER:\nOutput:\n" + o + "\n")
    return "".join(out)


def trim(full):
    """Verbatim port of AppworldPromptedLMModel.truncate_input
    (experiments/code/legacy/recoma/appworld_prompted_lm.py:22-39).

    init_prompt = everything up to and including the line holding the LAST "Task:" --
    so the whole instruction block and the task statement always survive. Only the
    interaction history is trimmed, and it is trimmed from the LEFT (oldest turns), so
    the tail -- which is where the intervention point sits -- is never touched.
    """
    goal_index = full.rfind("Task:")
    if goal_index == -1:
        raise ValueError("No goal found in input string")
    nl = full.find("\n", goal_index) + 1
    init_prompt, prompt = full[:nl], full[nl:]
    if len(init_prompt) > MAX_PROMPT_CHARS:
        raise ValueError("Input prompt longer than max allowed length")
    if len(prompt) > MAX_PROMPT_CHARS - len(init_prompt):
        new_prompt = prompt[-(MAX_PROMPT_CHARS - len(init_prompt)):]
        cmd = new_prompt.find("ASSISTANT:") if "ASSISTANT:" in new_prompt else 0
        prompt = "\n[TRIMMED HISTORY]\n\n" + new_prompt[cmd:]
    return init_prompt + prompt


def to_messages(prompt):
    """add_roles=true: split on the USER:/ASSISTANT: markers."""
    parts = re.split(r'(?m)^(USER:|ASSISTANT:)\s*$', prompt)
    msgs, role = [], "user"
    buf = parts[0].strip()
    if buf:
        msgs.append({"role": "user", "content": buf})
    i = 1
    while i < len(parts) - 1:
        role = "user" if parts[i] == "USER:" else "assistant"
        body = parts[i + 1].strip()
        if body:
            msgs.append({"role": role, "content": body})
        i += 2
    return msgs


def build(task_id, blocks, fail_idx, arm_response):
    instr, spec = fill_instructions(task_id)
    full = instr + history_text(blocks, fail_idx, last_output_override=arm_response)
    trimmed = trim(full)
    return dict(full=full, trimmed=trimmed, messages=to_messages(trimmed), spec=spec)
