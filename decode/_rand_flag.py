#!/usr/bin/env python3
"""Find offsets that act as a sparse small toggle across blocks.
For each steps-offset, compute the modal (default) value; report offsets where
only a few blocks deviate AND the deviation is small (<=4 abs), listing which
blocks deviate and to what. Good for lock flags / phase / slew.
Usage: _rand_flag.py FILE start end [maxdev]
"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import t1_blockdiff as bd

def s8(v): return v - 256 if v >= 128 else v

def main(argv):
    f = argv[0]; lo = int(argv[1]); hi = int(argv[2])
    maxdev = int(argv[3]) if len(argv) > 3 else 8
    idx = list(range(lo, hi + 1))
    blocks = bd.collect([f"{f}:{i}" for i in idx])
    n = len(blocks)
    sos = [b["so"] for b in blocks]; ends = [b["block_end"] for b in blocks]
    maxoff = min(e - s for e, s in zip(ends, sos))
    print(f"# {n} blocks {idx} (rel-index shown)")
    for off in range(maxoff):
        vals = [b["data"][b["so"] + off] for b in blocks]
        if len(set(vals)) == 1:
            continue
        mode = collections.Counter(vals).most_common(1)[0][0]
        dev = [(i, vals[i]) for i in range(n) if vals[i] != mode]
        if len(dev) == 0 or len(dev) > 8:
            continue
        if all(abs(s8(v) - s8(mode)) <= maxdev for _, v in dev):
            tag = bd.STEPS_FIELDS.get(off, "")
            devstr = ", ".join(f"b{i}->{v}" for i, v in dev)
            print(f"  +{off:#05x} {tag:>10} mode={mode}: {devstr}")

if __name__ == "__main__":
    main(sys.argv[1:])
