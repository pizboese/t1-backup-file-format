#!/usr/bin/env python3
"""Decode T-1 custom (user) scales — the structural novelty in bank 22.

KEY FINDING
-----------
The byte run that `t1_format.find_runs` keys on as the block "landmark" —
`00 01 02 03 04 05 06 07 08 09 0a 0b` — is NOT a magic marker. It is the
SCALE-DEGREE TABLE of the track, in its default (chromatic / all-notes) state:

    <count:u32 LE> <count bytes, each a semitone 0..11, ascending>

Default scale = chromatic = count 12, degrees [0,1,...,11]  -> looks like `0c 00 00 00`
followed by `00 01 02 ... 0b`. That is why a default block always contains the
"landmark".

When a track uses a CUSTOM / USER scale (scale enum byte `steps+0x40` == 7), the
table is rewritten to list only the enabled semitones, e.g. C+E+G -> count 3,
degrees [0,4,7]. The identity run is destroyed, so `find_runs` skips the block —
which is exactly why bank 22's 8 custom-scale tracks (T9..T16) sit in an
un-parsed ~7 KB gap.

This module locates every scale-degree table in a .t1 by scanning for the
`<count u32><ascending semitones>` shape immediately after a track's
`3c 00` (pitch=C) header, independent of the landmark.
"""
import os
import sys

NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def find_scale_tables(data, lo=0, hi=None):
    """Yield (addr, count, degrees) for every plausible scale-degree table.

    Heuristic: a u32 count in 1..12 followed by `count` strictly-ascending
    semitone bytes (<12), with a `3c` (pitch C) byte in the 8 bytes before it
    (the track's pitch header). Catches both default (identity) and custom tables.
    """
    if hi is None:
        hi = len(data)
    out = []
    i = lo
    while i < hi - 4:
        c = int.from_bytes(data[i:i + 4], "little")
        if 1 <= c <= 12:
            degs = list(data[i + 4:i + 4 + c])
            if all(d < 12 for d in degs) and all(degs[k] < degs[k + 1] for k in range(len(degs) - 1)):
                if 0x3c in data[i - 8:i]:
                    out.append((i, c, degs))
                    i += 4 + c
                    continue
        i += 1
    return out


def degrees_to_names(degs):
    return "+".join(NOTE[d] for d in degs)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(os.path.dirname(__file__), "samples/22_groove_tonal/22_groove_tonal.t1")
    data = open(path, "rb").read()
    tables = find_scale_tables(data)
    custom = [t for t in tables if t[2] != list(range(12))]
    print(f"{path}: {len(tables)} scale tables, {len(custom)} non-chromatic (custom)")
    for addr, c, degs in custom:
        print(f"  @{addr:#08x} count={c:2d} degrees={degs} = {degrees_to_names(degs)}")


if __name__ == "__main__":
    main()
