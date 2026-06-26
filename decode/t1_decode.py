#!/usr/bin/env python3
"""Additive field reporting for the decode campaign — layered on top of the shipped parser.

Keep new field decoders HERE (not in t1_format.py) so the product parser stays minimal and its
behavior unchanged. As a field is confirmed, its reader can be promoted into t1_format.py and the
note folded into the canonical FORMAT.md.

Usage:
    python3 decode/t1_decode.py FILE.t1        # shipped parse + the campaign's located fields
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import t1_format as F


# --- located-but-not-yet-canonical steps-region fields (offsets relative to the `steps` field) ---
# Source: root plan Part 1 / FORMAT_DECODE.md scoreboard. Fill in as the campaign confirms each.
# name -> (offset_from_steps, kind)  where kind in {"u8","s8","u16le","enum"}
LOCATED_FIELDS = {
    # already canonical (mirrored here for the report; authoritative reader is t1_format):
    # "probability": (0x79, "s8"), "timing_amount": (0xba, "s8"), "delay": (0x13e, "s8"),
    # "track_length": (0x14b, "enum"), "free_division": (0x299, "u8"),
}


def steps_field_offset(data, run, block_hi):
    """Return the file offset of the `steps` field for a block, reusing the parser's own math."""
    t = F.parse_track(data, run, block_hi=block_hi)
    term = 1 if t["summary_form"] else 0
    return t["block_end"] - F.TAIL_AFTER_STEPS - term


def report(path):
    data = open(path, "rb").read()
    runs = F.find_runs(data)
    starts = [F._pitch_count_and_start(data, r)[1] for r in runs]
    his = starts[1:] + [len(data)]
    print(f"{path}: {len(runs)} block(s)")
    for j, r in enumerate(runs):
        t = F.parse_track(data, r, block_hi=his[j])
        so = steps_field_offset(data, r, his[j])
        print(f"  trk#{t.get('position','?')} run={r:#x} steps_off={so:#x} "
              f"steps={t['steps']} div={t['division_ticks']} root={t['root']}")
        for name, (off, kind) in LOCATED_FIELDS.items():
            raw = data[so + off]
            val = raw - 256 if (kind == "s8" and raw > 127) else raw
            print(f"      {name:16s} +{off:#05x} = {val}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for p in sys.argv[1:]:
        report(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
