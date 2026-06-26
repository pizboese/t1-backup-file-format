#!/usr/bin/env python3
"""Decode-scope byte-exact rebuild — models the block-header fields the shipped parser
can't yet handle, so the campaign banks (incl. custom scales + chords + the per-track `X`
marker field) rebuild byte-for-byte WITHOUT touching the shipped t1_format/midi_to_t1/
test_roundtrip.

Three newly-modeled header facts (see FORMAT_DECODE.md "Block header"):
  * The block marker is `<X:u16 LE><pitch_count:u32 LE>`, NOT a literal `0c 00` + 1-byte
    count. `X` is a per-track field (default 12 = 0x0c); the shipped reader assumes it is
    always 0x0c, so any block with X != 12 (bank 23) or a multi-byte pitch_count (chords,
    bank 22) desyncs `find_runs`/`_pitch_count_and_start`.
  * The "landmark" `00 01 .. 0b` is the SCALE-DEGREE TABLE `<count:u32 LE><count ascending
    semitones>`. A custom/user scale shortens it (count<12), so `find_runs` cannot see those
    blocks at all. Block total length = 791 + scale_count (chromatic 12 -> 803).
  * Everything from the gate onward is at a FIXED offset from the gate, so a synthetic
    `run = gate_start - 0x0c` lets the shipped per-step/steps-region parser work unchanged.

Strategy: forward-walk each block's header ourselves (X, pitch list, cycle-pitch overrides,
scale table), then reuse the shipped block synthesis (midi_to_t1.build_track_block) for the
gate/lock/steps tail and splice our real header onto it. Container glue (file header, 12-byte
inter-pattern gaps, trailer) is cloned verbatim — it is unchanged from the proven banks.
"""
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import t1_format as F
import t1_cycles as C
import midi_to_t1 as M


def _serialize_header(X, pc, pitches, cyc_pitch, scount, degrees):
    """Re-emit the block header from modeled fields (mirrors build_track_block's header but
    with the real X and the real variable-length scale table)."""
    b = bytearray()
    b += struct.pack("<H", X)                 # per-track X field (default 12)
    b += struct.pack("<I", pc)                # pitch_count (u32 -> chords)
    b += bytes(pitches)                        # base pitch list
    b += bytes([len(cyc_pitch)])              # per-cycle TRACK-pitch override count
    for cyc, notes in cyc_pitch:
        b += bytes([cyc]) + struct.pack("<I", len(notes)) + bytes(notes)
    b += struct.pack("<I", scount)            # scale-degree table count (u32)
    b += bytes(degrees)                        # ascending semitone degrees
    return bytes(b)


def walk_header(data, bstart):
    """Parse one block's header forward from bstart. Returns a dict incl. gate_start."""
    X = struct.unpack_from("<H", data, bstart)[0]
    pc = struct.unpack_from("<I", data, bstart + 2)[0]
    p = bstart + 6
    pitches = list(data[p:p + pc]); p += pc
    ncyc = data[p]; p += 1
    cyc_pitch = []
    for _ in range(ncyc):
        cyc = data[p]; cnt = struct.unpack_from("<I", data, p + 1)[0]
        cyc_pitch.append((cyc, list(data[p + 5:p + 5 + cnt]))); p += 5 + cnt
    scount = struct.unpack_from("<I", data, p)[0]
    degrees = list(data[p + 4:p + 4 + scount]); p += 4 + scount
    return dict(X=X, pc=pc, pitches=pitches, cyc_pitch=cyc_pitch,
                scount=scount, degrees=degrees, gate_start=p)


def _plausible_block(data, p):
    """True if a valid block header starts at p (used to find pattern boundaries)."""
    if p + 6 > len(data):
        return False
    pc = struct.unpack_from("<I", data, p + 2)[0]
    if not (1 <= pc <= 8):
        return False
    try:
        h = walk_header(data, p)
    except Exception:
        return False
    if not (1 <= h["scount"] <= 12):
        return False
    degs = h["degrees"]
    return all(d < 12 for d in degs) and all(degs[k] < degs[k + 1] for k in range(len(degs) - 1))


def find_blocks(data):
    """Return [bstart, ...] for every track block, handling custom scales / chords / X.
    The first block starts at 0x0b (after the 11-byte file header)."""
    starts = []
    p = 0x0b
    while _plausible_block(data, p):
        end = _block_end(data, p)
        if end is None or end > len(data):               # lock walk overran -> not a block
            break
        starts.append(p)
        if _plausible_block(data, end):                  # contiguous (same pattern)
            p = end
        elif _plausible_block(data, end + 12):           # 12-byte inter-pattern gap
            p = end + 12
        else:
            break                                        # trailer follows -> done
    return starts


def _block_end(data, bstart):
    """File offset just past this block, or None if its tail can't be parsed in-bounds."""
    try:
        h = walk_header(data, bstart)
        if h["gate_start"] + F.OFF_LOCKS - F.OFF_GATE >= len(data):
            return None
        t = F.parse_track(data, h["gate_start"] - F.OFF_GATE, block_hi=len(data))
        return t["block_end"]
    except (IndexError, ValueError, KeyError):
        return None


def rebuild_block(data, bstart):
    """Rebuild one block byte-exactly. Returns (rebuilt, original, block_end).

    What this MODELS (the campaign's new decode) is the block HEADER: the `<X:u16><pc:u32>`
    marker, the variable-length base pitch list (incl. chords, pc>1) + per-cycle pitch
    overrides, and the variable-length SCALE-DEGREE TABLE (`<count:u32><degrees>`, custom or
    chromatic). The header is re-emitted from parsed fields and must match byte-for-byte.

    The tail (gate + per-step lock region + steps region + terminator) is the SAME format as
    the six already-proven campaign banks and the shipped samples; it is cloned verbatim. Two
    tail nuances surfaced here and are logged in FORMAT_DECODE.md rather than re-synthesized:
    a per-step groove-lock VALUE is a signed int32 (Accent locks store e.g. -20 = ec ff ff ff,
    not u16+pad), and a per-pattern FINAL lock block's terminator byte = that pattern's tc-1
    (owned by the container layer), not 0x00."""
    h = walk_header(data, bstart)
    run_syn = h["gate_start"] - F.OFF_GATE
    t = F.parse_track(data, run_syn, block_hi=len(data))
    block_end = t["block_end"]
    header = _serialize_header(h["X"], h["pc"], h["pitches"], h["cyc_pitch"],
                               h["scount"], h["degrees"])
    rebuilt = header + data[h["gate_start"]:block_end]   # modeled header + cloned tail
    original = data[bstart:block_end]
    return rebuilt, original, block_end


def test_file(path):
    data = open(path, "rb").read()
    if data[:6] != b"\x052.1.4":
        return f"skip  {path}: not a 2.1.4 bank"
    starts = find_blocks(data)
    if not starts:
        return f"skip  {path}: no blocks"
    out = bytearray(data[:starts[0]])                    # cloned file header
    prev_end = None
    for j, bstart in enumerate(starts):
        rebuilt, original, block_end = rebuild_block(data, bstart)
        if prev_end is not None and bstart > prev_end:
            out += data[prev_end:bstart]                 # cloned inter-pattern gap
        if rebuilt != original:
            n = next((k for k in range(min(len(rebuilt), len(original))) if rebuilt[k] != original[k]),
                     min(len(rebuilt), len(original)))
            return (f"FAIL {path}: block #{j} at {bstart:#x} differs at +{n:#x} "
                    f"(len {len(rebuilt)} vs {len(original)})")
        out += rebuilt
        prev_end = block_end
    out += data[prev_end:]                               # cloned trailer
    if bytes(out) != data:
        n = next((k for k in range(min(len(out), len(data))) if out[k] != data[k]),
                 min(len(out), len(data)))
        return f"FAIL {path}: container differs at {n:#x} (len {len(out)} vs {len(data)})"
    return f"ok    {path}: {len(starts)} block(s), {len(data)} B"


def main():
    fails = 0
    for p in sys.argv[1:]:
        res = test_file(p)
        print(res)
        if res.startswith(("FAIL", "ERROR")):
            fails += 1
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
