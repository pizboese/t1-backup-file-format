#!/usr/bin/env python3
"""Roundtrip the campaign backups under decode/samples/ ONLY — kept separate from the shipped
test_roundtrip.py so a freshly-acquired, not-yet-modeled field can be red here without turning
the product's regression suite red.

Reuses test_roundtrip.test_file (the per-bank byte-exact rebuild). Run from the repo root:
    python3 decode/test_decode.py
"""
import glob
import os
import sys

# run from repo root so relative imports + sample globs resolve like test_roundtrip
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import t1_format as F
import test_roundtrip as R


def main():
    paths = sorted(glob.glob("decode/samples/**/*.t1", recursive=True))
    paths += [p for p in sys.argv[1:] if p.endswith(".t1")]
    if not paths:
        print("no campaign samples yet under decode/samples/ — nothing to roundtrip")
        return 0
    fails = 0
    for p in paths:
        try:
            data = open(p, "rb").read()
            if data[:6] != b"\x052.1.4":
                continue
            if len(F.find_runs(data)) == 0:
                print(f"skip  {p}: empty bank"); continue
            res = R.test_file(p)
        except Exception as e:
            res = f"ERROR {p}: {e}"
        print(res)
        if res.startswith(("FAIL", "ERROR")):
            fails += 1
    print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED (expected until the field is modeled)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
