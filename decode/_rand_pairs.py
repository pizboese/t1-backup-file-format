#!/usr/bin/env python3
"""Find per-param random-amount offsets via the min/max PAIR signature.
For 16 blocks (8 pairs), the true amount byte for pair p is nonzero ONLY on
blocks 2p (min/neg) and 2p+1 (max/pos), zero elsewhere (other params default 0).
Flag offsets whose signed values are ~0 everywhere except exactly one adjacent
pair with opposite signs.
Usage: _rand_pairs.py FILE start end
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import t1_blockdiff as bd

def s8(v): return v - 256 if v >= 128 else v

def main(argv):
    f = argv[0]; lo = int(argv[1]); hi = int(argv[2])
    idx = list(range(lo, hi + 1))
    blocks = bd.collect([f"{f}:{i}" for i in idx])
    n = len(blocks)
    sos = [b["so"] for b in blocks]; ends = [b["block_end"] for b in blocks]
    maxoff = min(e - s for e, s in zip(ends, sos))
    print(f"# {n} blocks {idx}")
    for off in range(maxoff):
        vals = [b["data"][b["so"] + off] for b in blocks]
        if len(set(vals)) == 1:
            continue
        sv = [s8(v) for v in vals]
        # find nonzero positions (abs>=2 to ignore tiny noise)
        nz = [i for i, x in enumerate(sv) if abs(x) >= 2]
        # candidate: exactly the two members of one pair, opposite signs
        good = False
        for p in range((n)//2):
            a, b2 = 2*p, 2*p+1
            others = [i for i in range(n) if i not in (a, b2)]
            if all(abs(sv[i]) <= 1 for i in others) and sv[a] != 0 and sv[b2] != 0 and (sv[a] < 0) != (sv[b2] < 0):
                good = True; pairno = p; break
        tag = bd.STEPS_FIELDS.get(off, "")
        if good:
            print(f"  *PAIR{pairno}* +{off:#05x} {tag:>10}: s8={sv}")

if __name__ == "__main__":
    main(sys.argv[1:])
