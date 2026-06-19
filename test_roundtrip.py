#!/usr/bin/env python3
"""Self-test: prove midi_to_t1 block + container synthesis is byte-exact by rebuilding
existing known-good sample banks from their own parsed fields and stored-state."""
import glob
import struct
import sys

import t1_format as F
import midi_to_t1 as M

PARAM_CODE = {"velocity": M.PARAM_VELOCITY, "sustain": M.PARAM_SUSTAIN}


def block_template_and_fields(data, run):
    """Extract (template, build kwargs) for an existing block so build_track_block
    reproduces it exactly."""
    pc, bstart = F._pitch_count_and_start(data, run)
    groove, pitch, so = F._parse_locks(data, run)
    block_end = so + F.TAIL_AFTER_STEPS + (1 if (groove or pitch) else 0)
    filler_a = data[run + M.OFF_GATE + 16: run + M.OFF_LOCKS]
    steps_region = data[so: so + F.TAIL_AFTER_STEPS]
    t = F.parse_track(data, run)
    # groove_locks come back as {step:{name:val}}; rebuild needs raw param codes via name
    groove_locks = {step: {name: val for name, val in d.items()}
                    for step, d in groove.items()}
    fields = dict(
        gate=t["gate"], pitches=t["pitches"], steps=t["steps"],
        division=t["division_ticks"], scale=t["scale"], root=t["root"],
        velocity=t["velocity"], sustain=t["sustain"], mask=t["midi_mask"],
        pitch_locks=pitch, groove_locks=groove_locks,
    )
    return (filler_a, steps_region), fields, data[bstart:block_end]


def test_file(path):
    data = open(path, "rb").read()
    runs = F.find_runs(data)
    # the bank's final block, if it carries locks, uses a special terminator (byte = last_tc-1,
    # plus a pad on multi-pattern banks) applied by build_bank, not build_track_block — so its
    # per-block terminator legitimately differs; validate its body here, terminator in step 2.
    last_locks = F.parse_track(data, runs[-1]) if runs else None
    final_has_locks = bool(last_locks and (last_locks["pitch_locks"] or last_locks["groove_locks"]))
    # 1) every block rebuilds byte-identically
    rebuilt_blocks = []
    for j, r in enumerate(runs):
        template, fields, original = block_template_and_fields(data, r)
        rebuilt = M.build_track_block(template, **fields)
        cmp_r, cmp_o = rebuilt, original
        if j == len(runs) - 1 and final_has_locks:
            cmp_r, cmp_o = rebuilt[:-1], original[:-1]      # ignore final terminator byte
        if cmp_r != cmp_o:
            n = next((k for k in range(min(len(cmp_r), len(cmp_o)))
                      if cmp_r[k] != cmp_o[k]), min(len(cmp_r), len(cmp_o)))
            return f"FAIL {path}: block at run {r:#x} differs at +{n:#x} "\
                   f"(len {len(rebuilt)} vs {len(original)})"
        rebuilt_blocks.append(rebuilt)
    # 2) container rebuilds byte-identically (skip the 23-byte empty bank)
    if len(runs) == 0:
        return f"skip  {path}: empty bank"
    tracks = [F.parse_track(data, r) for r in runs]
    pats = F.group_patterns(tracks)
    # slice rebuilt_blocks into the same pattern grouping; recover real slot indices from
    # each pattern's 4-byte gap header (first pattern is slot 0)
    patterns, indices, idx = [], [0], 0
    for k, p in enumerate(pats):
        patterns.append(rebuilt_blocks[idx:idx + len(p)])
        if k > 0:
            indices.append(data[p[0]["block_start"] - 4])      # slot byte in the gap header
        idx += len(p)
    rebuilt_bank = M.build_bank(patterns, current_pattern=data[-11], indices=indices,
                                final_has_locks=final_has_locks)
    if rebuilt_bank != data:
        n = next((k for k in range(min(len(rebuilt_bank), len(data)))
                  if rebuilt_bank[k] != data[k]), min(len(rebuilt_bank), len(data)))
        return f"FAIL {path}: bank differs at {n:#x} (len {len(rebuilt_bank)} vs {len(data)})"
    return f"ok    {path}: {len(runs)} block(s), {len(pats)} pattern(s), {len(data)} B"


def main():
    paths = sorted(glob.glob("samples/**/*.t1", recursive=True))
    fails = 0
    for p in paths:
        try:
            data = open(p, "rb").read()
            if data[:6] != b"\x052.1.4":
                continue
            if len(F.find_runs(data)) == 0:
                print(f"skip  {p}: empty bank"); continue
            res = test_file(p)
        except Exception as e:
            res = f"ERROR {p}: {e}"
        print(res)
        if res.startswith(("FAIL", "ERROR")):
            fails += 1
    print(f"\n{'ALL PASS' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
