#!/usr/bin/env python3
"""Self-test: prove midi_to_t1 block + container synthesis is byte-exact by rebuilding
existing known-good sample banks from their own parsed fields and stored-state."""
import glob
import struct
import sys

import t1_format as F
import t1_cycles as C
import midi_to_t1 as M

PARAM_CODE = {"velocity": M.PARAM_VELOCITY, "sustain": M.PARAM_SUSTAIN}


def block_template_and_fields(data, run, block_hi):
    """Extract (template, build kwargs) for an existing block so build_track_block
    reproduces it exactly — including steps-64 + cycle structures."""
    pc, bstart = F._pitch_count_and_start(data, run)
    t = F.parse_track(data, run, block_hi=block_hi)
    # locks may live in the base track OR a per-cycle record; both add the terminator that
    # parse_track folds into block_end, so subtract the FULL terminator to recover `steps`.
    cyc = C.parse_for_rebuild(data, run, block_hi)
    # A "summary" block (carries locks OR is a device-authored summary-but-lockless block, e.g.
    # project.zip's first track) has a trailing terminator byte and its end-marker at 0x2b6;
    # a plain block has neither (marker at 0x2b5). parse_track flags this as `summary_form`.
    term = 1 if t["summary_form"] else 0
    so = t["block_end"] - F.TAIL_AFTER_STEPS - term          # parse's own steps offset
    block_end = t["block_end"]
    steps_region = data[so: so + F.TAIL_AFTER_STEPS]
    # base groove locks raw (param-id keyed) for exact rebuild
    groove_raw, pitch_raw, _ = C._parse_lock_list_raw(data, run + F.OFF_LOCKS)
    end_mark = steps_region[0x2b6 if t["summary_form"] else 0x2b5]
    fields = dict(
        gate=t["gate"], pitches=t["pitches"], steps=t["steps"],
        division=t["division_ticks"], scale=t["scale"], root=t["root"],
        velocity=t["velocity"], sustain=t["sustain"], mask=t["midi_mask"],
        pitch_locks=pitch_raw, groove_locks=groove_raw, end_mark=end_mark,
        cycles=t["cycles"], step_group=t["step_group"],
        cycle_pitch=cyc["cycle_pitch"], cycle_records=cyc["cycle_records"],
        cycle_params=cyc["cycle_params"],
    )
    return (None, steps_region), fields, data[bstart:block_end]


def test_file(path):
    data = open(path, "rb").read()
    runs = F.find_runs(data)
    starts = [F._pitch_count_and_start(data, r)[1] for r in runs]
    his = starts[1:] + [len(data)]
    # the bank's final block, if it carries locks, uses a special terminator (byte = last_tc-1,
    # plus a pad on multi-pattern banks) applied by build_bank, not build_track_block — so its
    # per-block terminator legitimately differs; validate its body here, terminator in step 2.
    if runs:
        last_locks = F.parse_track(data, runs[-1], block_hi=his[-1])
        last_cyc = C.parse_for_rebuild(data, runs[-1], his[-1])
        final_has_locks = bool(last_locks["pitch_locks"] or last_locks["groove_locks"]
                               or any(g or p for _, _, g, p in last_cyc["cycle_records"]))
    else:
        final_has_locks = False
    # 1) every block rebuilds byte-identically
    rebuilt_blocks = []
    for j, r in enumerate(runs):
        template, fields, original = block_template_and_fields(data, r, his[j])
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
    tracks = [F.parse_track(data, r, block_hi=h) for r, h in zip(runs, his)]
    pats = F.group_patterns(tracks)
    # slice rebuilt_blocks into the same pattern grouping; recover real slot indices from
    # each pattern's 4-byte gap header (first pattern is slot 0)
    patterns, indices, cursors, first_slots, idx = [], [0], [], [], 0
    for k, p in enumerate(pats):
        patterns.append(rebuilt_blocks[idx:idx + len(p)])
        # first serialized track's slot: byte 0x09 (pattern 0) / gap-header 3rd byte (block-2)
        first_slots.append((data[0x09] if k == 0 else data[p[0]["block_start"] - 2]) + 1)
        if k > 0:
            indices.append(data[p[0]["block_start"] - 4])      # slot byte in the gap header
        # per-pattern saved track cursor = trailer[+2]. Read from the trailer's actual file
        # position (robust to the Form-X final terminator+pad): each non-final pattern's trailer
        # sits 12 B before the next pattern's first block; the final one 8 B before the summary.
        if k < len(pats) - 1:
            cursors.append(data[pats[k + 1][0]["block_start"] - 12 + 2])
        else:
            cursors.append(data[len(data) - 16 - 8 + 2])       # before 12B summary + "os|t"
        idx += len(p)
    rebuilt_bank = M.build_bank(patterns, current_pattern=data[-11], indices=indices,
                                final_has_locks=final_has_locks, track_cursors=cursors,
                                first_slots=first_slots)
    if rebuilt_bank != data:
        n = next((k for k in range(min(len(rebuilt_bank), len(data)))
                  if rebuilt_bank[k] != data[k]), min(len(rebuilt_bank), len(data)))
        return f"FAIL {path}: bank differs at {n:#x} (len {len(rebuilt_bank)} vs {len(data)})"
    return f"ok    {path}: {len(runs)} block(s), {len(pats)} pattern(s), {len(data)} B"


def main():
    paths = sorted(glob.glob("samples/**/*.t1", recursive=True))
    paths += [p for p in sys.argv[1:] if p.endswith(".t1")]   # extra banks (e.g. cycle backups)
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
