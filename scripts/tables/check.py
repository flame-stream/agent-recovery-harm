#!/usr/bin/env python3
"""Compare the values computed by paper_numbers.py with paper/expected_values.json.
Exit code 1 on any difference. Nothing is rounded or adjusted to fit."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
out = ROOT / "build" / "paper_numbers.json"
out.parent.mkdir(exist_ok=True)
subprocess.run([sys.executable, str(ROOT / "scripts/tables/paper_numbers.py"), "--json", str(out)],
               check=True, stdout=subprocess.DEVNULL)
got = json.load(open(out))
exp = json.load(open(ROOT / "paper/expected_values.json"))
bad = skipped = 0
for e in exp:
    k, want = e["key"], e["expected"]
    have = got.get(k, "<missing>")
    if have == "<missing>" and e.get("needs") == "unpack":     # computed from the bundle only
        skipped += 1
        print(f"skip {k:45s} needs `make unpack` (data/protected/)   [{e['claim']}]")
        continue
    ok = have == want
    bad += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {k:45s} expected {json.dumps(want, ensure_ascii=False)}"
          + ("" if ok else f"  got {json.dumps(have, ensure_ascii=False)}") + f"   [{e['claim']}]")
print(f"\n{len(exp) - bad - skipped} of {len(exp)} values match"
      + (f"; {skipped} not checked: run `make unpack` first" if skipped else ""))
sys.exit(1 if bad else 0)
