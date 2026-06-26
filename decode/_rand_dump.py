#!/usr/bin/env python3
"""Dump steps-relative byte values across a set of blocks (aligned via t1_blockdiff.collect).
Usage:
  _rand_dump.py FILE start end            # blocks start..end inclusive
  _rand_dump.py FILE i j k ...            # explicit block indices
Then prints, per steps-offset that VARIES, the value list, plus a 'shape' flag:
  MONO+ = strictly increasing, NONDEC = non-decreasing, and signed-s8 view.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import t1_blockdiff as bd

def s8(v): return v - 256 if v >= 128 else v

def main(argv):
    f = argv[0]
    if len(argv) == 3 and argv[1].isdigit() and argv[2].isdigit():
        idx = list(range(int(argv[1]), int(argv[2]) + 1))
    else:
        idx = [int(x) for x in argv[1:]]
    specs = [f"{f}:{i}" for i in idx]
    blocks = bd.collect(specs)
    n = len(blocks)
    # build steps-relative byte arrays
    sos = [b["so"] for b in blocks]
    ends = [b["block_end"] for b in blocks]
    maxoff = min(e - s for e, s in zip(ends, sos))
    rows = {}
    for off in range(0, maxoff):
        vals = [b["data"][b["so"] + off] for b in blocks]
        if len(set(vals)) == 1:
            continue
        rows[off] = vals
    print(f"# {n} blocks {idx}, {len(rows)} varying steps-offsets, maxoff={maxoff:#x}")
    for off, vals in rows.items():
        sv = [s8(v) for v in vals]
        nondec = all(vals[i] <= vals[i+1] for i in range(n-1))
        nondec_s = all(sv[i] <= sv[i+1] for i in range(n-1))
        flags = []
        if nondec: flags.append("NONDEC")
        if nondec_s: flags.append("NONDEC_s8")
        tag = bd.STEPS_FIELDS.get(off, "")
        f2 = (" <" + ",".join(flags) + ">") if flags else ""
        print(f"  +{off:#05x} {tag:>10}: {vals}  s8={sv}{f2}")

if __name__ == "__main__":
    main(sys.argv[1:])
