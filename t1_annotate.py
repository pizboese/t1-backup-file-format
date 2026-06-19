#!/usr/bin/env python3
"""
t1_annotate.py — Torso T-1 .t1 backup format reverse-engineering helper.

Usage:
  t1_annotate.py show   FILE...            annotated dump of each file
  t1_annotate.py diff   FILE_A FILE_B      byte diff, grouped into runs
  t1_annotate.py sweep  FILE...            per-offset value table across files;
                                           flags offsets whose values increase
                                           monotonically (1-per-index) — the
                                           signature of a swept parameter.

The format is a flat, deterministic serialization. Known skeleton (firmware 2.1.4):

  0x00        u8   len of version string (0x05)
  0x01..0x05  str  "2.1.4"
  0x06        u8   has-content flag (0x00 empty bank, 0x01 has content)
  0x07..0x22  ...  fixed skeleton (counts; includes 0c=12, 3c=60, and a 0..11 run)
  0x23..0x32  16x  STEP/GATE array, one byte per step (0x01=pulse, 0x00=empty)
  0x33..0x76  00   zero padding
  0x77..      ...  per-track stored "random sequence" region (high entropy, stable)
  tail        ...  78 00*6 01 00*4 "os|t"  (constant footer)

Offsets/labels are refined as more of the format is decoded.
"""
import sys

VERSION_LEN_OFF = 0x00
FLAG_OFF = 0x06
SKELETON = (0x07, 0x23)        # [start, end)
STEP_ARRAY = (0x23, 0x33)      # 16 bytes, one per step
ZERO_PAD = (0x33, 0x77)
RANDOM_REGION = (0x77, None)   # to start of footer; end filled in per-file
FOOTER_MAGIC = b"os|t"


def load(path):
    with open(path, "rb") as f:
        return f.read()


def parse(data):
    """Return a dict of decoded fields; tolerant of the tiny empty-bank file."""
    out = {"size": len(data)}
    vlen = data[VERSION_LEN_OFF]
    out["version"] = data[1:1 + vlen].decode("latin1")
    out["flag"] = data[FLAG_OFF] if len(data) > FLAG_OFF else None
    out["has_footer"] = data.endswith(FOOTER_MAGIC)
    if len(data) >= STEP_ARRAY[1]:
        steps = data[STEP_ARRAY[0]:STEP_ARRAY[1]]
        out["steps"] = list(steps)
        out["pulse_steps"] = [i + 1 for i, b in enumerate(steps) if b]
    else:
        out["steps"] = None
        out["pulse_steps"] = []
    return out


def hexrow(data, off, length):
    chunk = data[off:off + length]
    h = " ".join(f"{b:02x}" for b in chunk)
    a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    return f"  {off:#06x}  {h:<48}  {a}"


def show(path):
    data = load(path)
    p = parse(data)
    print(f"== {path}  ({p['size']} bytes) ==")
    print(f"  version={p['version']!r}  flag={p['flag']}  footer={p['has_footer']}")
    if p["steps"] is None:
        print("  (empty bank — no payload)")
    else:
        print(f"  steps   = {p['steps']}")
        print(f"  pulses on steps: {p['pulse_steps']}")
        print("  step/gate array region:")
        print(hexrow(data, STEP_ARRAY[0], 16))
        print("  skeleton (0x07-0x22):")
        print(hexrow(data, 0x07, 16))
        print(hexrow(data, 0x17, 12))
    print()


def runs(diff_offsets):
    """Group sorted offsets into contiguous [start, end] runs."""
    out = []
    for o in diff_offsets:
        if out and o == out[-1][1] + 1:
            out[-1][1] = o
        else:
            out.append([o, o])
    return out


def diff(pa, pb):
    a, b = load(pa), load(pb)
    print(f"== diff {pa} ({len(a)}B) vs {pb} ({len(b)}B) ==")
    if len(a) != len(b):
        print(f"  size differs: {len(a)} vs {len(b)}")
    n = min(len(a), len(b))
    offs = [i for i in range(n) if a[i] != b[i]]
    if not offs:
        print("  IDENTICAL (over common length)")
        return
    for s, e in runs(offs):
        ha = " ".join(f"{a[i]:02x}" for i in range(s, e + 1))
        hb = " ".join(f"{b[i]:02x}" for i in range(s, e + 1))
        tag = annotate_region(s, e)
        print(f"  {s:#06x}-{e:#06x} [{tag}]")
        print(f"      A: {ha}")
        print(f"      B: {hb}")


def annotate_region(s, e):
    if e < STEP_ARRAY[0]:
        return "skeleton"
    if s >= STEP_ARRAY[0] and e < STEP_ARRAY[1]:
        return "STEP ARRAY"
    if s >= RANDOM_REGION[0]:
        return "random-seq"
    return "mixed/unknown"


def sweep(paths):
    """Across N files, print offsets where the byte value changes, and flag
    those that increase monotonically by exactly 1 per file (swept param)."""
    blobs = [load(p) for p in paths]
    n = min(len(b) for b in blobs)
    print(f"== sweep over {len(paths)} files (common {n} bytes) ==")
    for name in paths:
        print(f"   - {name}")
    mono, varying = [], []
    for off in range(n):
        vals = [b[off] for b in blobs]
        if len(set(vals)) == 1:
            continue
        varying.append((off, vals))
        diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        if all(d == 1 for d in diffs) or all(d == -1 for d in diffs):
            mono.append((off, vals))
    print(f"\n  {len(varying)} offsets vary; {len(mono)} are monotonic (+/-1 per step):\n")
    print("  MONOTONIC (likely the swept parameter / index byte):")
    for off, vals in mono:
        print(f"    {off:#06x} [{annotate_region(off, off)}]: {vals}")
    if not mono:
        print("    (none)")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "show":
        for p in argv[2:]:
            show(p)
    elif cmd == "diff":
        diff(argv[2], argv[3])
    elif cmd == "sweep":
        sweep(argv[2:])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
