#!/usr/bin/env python3
"""Monotonic-field scanner for the complete-decode campaign.

For a list of (file, block_index) pairs, align each block to its `steps` field and, for every
steps-region offset, print the N values across blocks and flag offsets whose sequence is
STRICTLY MONOTONIC (increasing or decreasing) by ANY constant-ish step. Also checks u16 LE pairs.

Usage:
    python3 decode/_scan_mono.py FILE.t1 i0 i1 i2 ...      # block indices into that file
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import t1_format as F

TAIL = F.TAIL_AFTER_STEPS  # 0x2b7 fixed steps-region length

KNOWN = {
    0x00: "steps", 0x2a: "div_lo", 0x2b: "div_hi", 0x40: "scale", 0x55: "pitch_run",
    0x79: "probability", 0x7b: "velocity", 0xa5: "sustain", 0xba: "timing_amt",
    0xe4: "out_mask", 0x13d: "style", 0x13e: "delay", 0x13f: "root", 0x146: "timing_sub",
    0x14b: "track_len", 0x14d: "cycles", 0x299: "free_div",
}
ZONE_A = {0x16, 0x68, 0x91, 0xbb, 0xd0, 0xfa, 0x110, 0x126}


def steps_off(data, run, hi):
    t = F.parse_track(data, run, block_hi=hi)
    term = 1 if t["summary_form"] else 0
    return t["block_end"] - TAIL - term


def load(path):
    data = open(path, "rb").read()
    runs = F.find_runs(data)
    starts = [F._pitch_count_and_start(data, r)[1] for r in runs]
    his = starts[1:] + [len(data)]
    sos = [steps_off(data, runs[j], his[j]) for j in range(len(runs))]
    return data, sos


def is_mono(vals):
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    if all(d > 0 for d in diffs):
        return "+", diffs
    if all(d < 0 for d in diffs):
        return "-", diffs
    return None, diffs


def main():
    path = sys.argv[1]
    idxs = [int(x) for x in sys.argv[2:]]
    data, sos = load(path)
    bsos = [sos[i] for i in idxs]
    n = len(bsos)
    print(f"# {path} blocks {idxs}  ({n} blocks)")
    # u8 scan
    print("\n## strictly-monotonic u8 / s8 offsets:")
    for off in range(0, TAIL):
        vals = [data[so + off] for so in bsos]
        if len(set(vals)) < 2:
            continue
        sign, diffs = is_mono(vals)
        if sign:
            svals = [v - 256 if v > 127 else v for v in vals]
            tag = KNOWN.get(off, "")
            if not tag:
                for z in ZONE_A:
                    if abs(off - z) <= 3:
                        tag = f"~ZoneA{z:#x}"
            print(f"  +{off:#05x} {sign} u8={vals}  s8={svals}  d={diffs}  {tag}")
    # u16 LE scan
    print("\n## strictly-monotonic u16-LE offsets:")
    for off in range(0, TAIL - 1):
        vals = [data[so + off] | (data[so + off + 1] << 8) for so in bsos]
        if len(set(vals)) < 2:
            continue
        sign, diffs = is_mono(vals)
        if sign:
            tag = KNOWN.get(off, "")
            print(f"  +{off:#05x} {sign} u16={vals}  d={diffs}  {tag}")


if __name__ == "__main__":
    main()
