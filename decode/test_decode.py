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
import decode.decode_rebuild as D


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
            # Prefer the shipped full-synthesis rebuild (exercises build_track_block + build_bank).
            # Custom-scale / chord / X-marker banks (22, 23) desync the shipped find_runs, so fall
            # back to the decode-local modeled-header rebuild (decode_rebuild). See decode/CLAUDE.md.
            res = R.test_file(p)
            if res.startswith(("FAIL", "ERROR")):
                alt = D.test_file(p)
                if alt.startswith("ok"):
                    res = alt + "  [decode-local: modeled header + cloned tail]"
        except Exception as e:
            res = f"ERROR {p}: {e}"
        print(res)
        if res.startswith(("FAIL", "ERROR")):
            fails += 1
    print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED (expected until the field is modeled)'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
