#!/usr/bin/env python3
"""
midi_to_t1.py — import Standard MIDI File(s) into a Torso T-1 per-bank `.t1` backup.

Usage:
  midi_to_t1.py -o OUT.t1 IN1.mid [IN2.mid ...] [options]

Each input `.mid` becomes one T-1 **pattern**; within a pattern, each MIDI channel
that carries notes becomes one T-1 **track** (max 16 patterns x 16 tracks). Notes are
quantized to a 16-step grid; chords and per-step pitch changes become per-step pitch
locks; per-step velocity / note-length changes become groove (velocity / sustain) locks.

Options:
  -o, --out FILE     output .t1 (required)
  --div N            grid/playback division (1,2,4,8,16,32,64,3,6,12,24,48); default 16
  --length N         loop length in steps (1..16); default 16 (full bar)
  --template FILE    .t1 whose first track block seeds the per-track "stored state"
                     region (default: samples/10_synth_test_import/0.t1)
  --bpm / ignored    tempo is a playback concern; the T-1 has its own clock.

Design: the format has no checksum (proven by on-device import). A track block contains a
large per-track "random sequence" region that is device-generated stored state; we clone it
from a known-good template block and patch in the fields we control, rebuilding the
variable-length pitch list and per-step lock lists. See FORMAT.md for the byte map.
"""
import os
import struct
import sys

import t1_format as F

# ── track-block geometry (block-relative / run-relative; see FORMAT.md) ─────────────
RUN = bytes(range(12))                 # 00 01 .. 0b landmark
OFF_GATE = F.OFF_GATE                  # 0x0c from run: 16-byte gate array
OFF_LOCKS = F.OFF_LOCKS                # 0x4c from run: lock region (groove then pitch)
PAD_AFTER_LOCKS = F.PAD_AFTER_LOCKS    # 18 zero bytes between lock lists and `steps`
FILLER_A_LEN = OFF_LOCKS - (OFF_GATE + 16)   # 0x30 = 48 bytes between gate and locks
STEPS_REGION_LEN = F.TAIL_AFTER_STEPS  # 0x2b7: `steps`..block end (fixed length)

# field offsets within the steps-region template (relative to `steps`)
SR_STEPS = 0x00
SR_DIVISION = F.S_DIVISION             # u16 LE
SR_SCALE = F.S_SCALE
SR_VELOCITY = F.S_VELOCITY
SR_SUSTAIN = F.S_SUSTAIN
SR_MIDIMASK = F.S_MIDIMASK             # u16 LE
SR_ROOT = F.S_ROOT
SR_STYLE = 0x13d                       # voicing Style: poly(chord)=0-4, mono(arp)=8-12; 0=Fixed
# trailing per-block lock-summary (see FORMAT.md "TRUE chord blocker"): a lock-bearing block
# carries `01 00 00 00 <K> 00` at steps+0x29c and ends `..00 01` instead of `..01 00`.
SR_LOCK_FLAG = 0x29c                   # 1 = block has locks (else 0)
SR_LOCK_CURSOR = 0x2a0                 # u16: cursor/last-edited locked step (cosmetic; use max)
SR_END_MARK = 0x2b5                    # non-lock: 01 00 ; lock: 00 01

PARAM_VELOCITY = 0x0a
PARAM_SUSTAIN = 0x0e
GROOVE_PARAM_CODE = {"velocity": PARAM_VELOCITY, "sustain": PARAM_SUSTAIN}

# division-name -> ticks/step @96 PPQN (value * divisor = 384); see FORMAT.md table
DIVISIONS = {1: 384, 2: 192, 4: 96, 8: 48, 16: 24, 32: 12, 64: 6,
             3: 128, 6: 64, 12: 32, 24: 16, 48: 8}

DEFAULT_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "samples", "10_synth_test_import", "0.t1")


# ── template extraction ─────────────────────────────────────────────────────────────
def load_template(path):
    """Pull the two device-generated 'stored state' chunks from a known-good track
    block: the 48-byte filler between gate and locks, and the 0x2b7-byte steps region."""
    data = open(path, "rb").read()
    run = F.find_runs(data)[0]
    _, _, so = F._parse_locks(data, run)
    filler_a = data[run + OFF_GATE + 16: run + OFF_LOCKS]
    steps_region = data[so: so + STEPS_REGION_LEN]
    if len(filler_a) != FILLER_A_LEN or len(steps_region) != STEPS_REGION_LEN:
        raise ValueError(f"{path}: unexpected template block geometry")
    return filler_a, steps_region


# ── track block synthesis ───────────────────────────────────────────────────────────
def build_track_block(template, *, gate, pitches, steps, division, scale, root,
                      velocity, sustain, mask, pitch_locks, groove_locks, end_mark=1):
    """Synthesize one 803+ byte track block by cloning `template` stored-state and
    patching the controllable fields + variable-length pitch/lock regions.

    gate          : iterable of up to 16 ints (0/1)
    pitches       : track-default pitch list (>=1 absolute notes, C3=60)
    pitch_locks   : {step0: [notes]}      per-step pitch overrides (incl. chords)
    groove_locks  : {step0: {'velocity'|'sustain': value}}  per-step groove overrides
    """
    filler_a, steps_region = template
    gate = list(gate)[:16] + [0] * max(0, 16 - len(gate))

    b = bytearray()
    b += b"\x0c\x00" + bytes([len(pitches)]) + b"\x00\x00\x00"   # block marker + pitch count
    b += bytes(pitches)                                          # pitch list (variable)
    b += b"\x00\x0c\x00\x00\x00"                                 # post-pitch constant
    b += RUN                                                     # 00..0b landmark
    b += bytes(gate)                                             # 16-byte gate array
    b += filler_a                                               # 48-byte stored filler

    # lock region: groove list, pitch list, 18-byte pad (lists stored newest/step-desc first).
    # A groove record packs all params for one step: [entry_count][step] + N*[param value 00 00 00].
    glocks = sorted(groove_locks.items(), reverse=True)          # step-desc
    b += bytes([len(glocks)])
    for step, gl in glocks:                                       # gl order preserved (newest-first)
        b += bytes([len(gl), step])
        for name, value in gl.items():
            b += bytes([GROOVE_PARAM_CODE[name], value, 0, 0, 0])

    plocks = sorted(pitch_locks.items(), reverse=True)           # step-desc
    b += bytes([len(plocks)])
    for step, notes in plocks:
        b += bytes([step]) + struct.pack("<I", len(notes)) + bytes(notes)
    b += b"\x00" * PAD_AFTER_LOCKS

    # steps region: clone template, patch documented fields
    sr = bytearray(steps_region)
    sr[SR_STEPS] = steps
    struct.pack_into("<H", sr, SR_DIVISION, division)
    sr[SR_SCALE] = scale
    sr[SR_VELOCITY] = velocity
    sr[SR_SUSTAIN] = sustain
    struct.pack_into("<H", sr, SR_MIDIMASK, mask)
    sr[SR_ROOT] = root
    # If the block carries locks but the template's steps-region is a NON-lock one (its lock
    # summary is absent), synthesize the trailing lock-summary the device requires; otherwise a
    # lock-bearing block cloned from a non-lock template mis-renders (chords) and drops a later
    # pattern. Skipped when the template already has the summary (e.g. self-templated roundtrip).
    if (pitch_locks or groove_locks) and sr[SR_LOCK_FLAG] == 0:
        locked_steps = set(pitch_locks) | set(groove_locks)
        sr[SR_LOCK_FLAG] = 1
        struct.pack_into("<H", sr, SR_LOCK_CURSOR, max(locked_steps))
        # end-marker at +0x2b6 (Form Y). Its value is position-dependent within the pattern: the
        # device drops a lock track whose value is wrong. Observed (device banks): first track=1,
        # otherwise N-i (N tracks, index i) -> e.g. 3-track pattern = [1,2,1], 2-track = [1,1],
        # 1-track = [1]. Caller passes end_mark; defaults to 1 (first/last/single).
        sr[SR_END_MARK] = 0; sr[SR_END_MARK + 1] = end_mark
    b += sr
    if pitch_locks or groove_locks:
        b += b"\x00"                               # lock terminator byte (see FORMAT.md)
    return bytes(b)


# ── bank (container) synthesis ──────────────────────────────────────────────────────
def build_bank(patterns, current_pattern=0, indices=None, final_has_locks=False):
    """Assemble a per-bank `.t1` from a list of patterns (each a list of track-block bytes).
    Header: 05 "2.1.4" npat 00 tc0 00 00. Patterns separated by 12 B (8 B end-trailer
    `00 00 (tc-1) 00 00 00 00 00` + 4 B next-pattern header `slot tc 00 00`). Bank trailer:
    8 B end-trailer + 12 B summary + "os|t".

    `indices` = the 0-based device pattern SLOT (0..15) for each serialized pattern; only
    used patterns are stored, so slots may be sparse (e.g. [0, 2] = Patterns 1 & 3). Defaults
    to contiguous 0..npat-1. `current_pattern` is the slot selected at backup time (a saved
    cursor embedded in the summary; the device opens the bank on it), default 0.

    `final_has_locks` = the bank's LAST block carries locks. The final lock terminator is
    special: its byte is `last_tc-1` (not the usual 0x00 of mid-bank lock blocks), and
    multi-pattern banks append one extra 0x00 pad before the bank trailer. (Device-observed;
    single-pattern banks like 08/09 have last_tc-1=0 so this is a no-op for them.) Verified
    against the device-authored multi-pattern reference. See FORMAT.md."""
    patterns = [list(p) for p in patterns if p]
    if not patterns:
        raise ValueError("no non-empty patterns to write")
    npat = len(patterns)
    if indices is None:
        indices = list(range(npat))
    cur = max(0, min(current_pattern, 15))
    if final_has_locks:                         # patch the bank's final lock terminator
        fb = bytearray(patterns[-1][-1])        # build_track_block left a 0x00 terminator here
        # The block's end-marker `01` must appear exactly ONCE near the tail. Two device-proven
        # layouts: Form X (marker at the terminator position, region end-byte=0 → terminator =
        # last_tc-1, e.g. samples/11) and Form Y (marker already at the region end-byte=1,
        # terminator stays 0, e.g. device-authored iteration3). build_track_block writes Form Y
        # for from-scratch lock blocks; only apply the Form-X terminator when the marker is NOT
        # already at the region end-byte, else the two `01`s collide and the device rejects the
        # whole bank. fb[-1]=appended terminator, fb[-2]=region end-byte (steps+0x2b6).
        if fb[-2] == 0:                         # Form X: terminator carries the marker
            fb[-1] = len(patterns[-1]) - 1      #   terminator = last_tc - 1
            if npat > 1:
                fb += b"\x00"                    #   + one pad byte (multi-pattern Form X only)
        # Form Y (marker already at the region end-byte): leave terminator 0, no pad.
        patterns[-1][-1] = bytes(fb)
    out = bytearray(b"\x052.1.4")
    out += bytes([npat, 0, len(patterns[0]), 0, 0])
    out += b"".join(patterns[0])
    for i in range(1, npat):
        prev_tc = len(patterns[i - 1])
        out += bytes([0, 0, prev_tc - 1, 0, 0, 0, 0, 0])        # end-of-prev-pattern trailer
        out += bytes([indices[i], len(patterns[i]), 0, 0])      # next-pattern header (slot, tc)
        out += b"".join(patterns[i])
    last_tc = len(patterns[-1])
    out += bytes([0, 0, last_tc - 1, 0, 0, 0, 0, 0])            # end-of-last-pattern trailer
    out += bytes([0x78, 0, 0, 0, 0, cur, cur, 1, 0, 0, 0, cur])  # bank summary
    out += b"os|t"
    return bytes(out)


# ── minimal Standard MIDI File reader (no deps) ─────────────────────────────────────
def _read_vlq(data, i):
    n = 0
    while True:
        b = data[i]; i += 1
        n = (n << 7) | (b & 0x7f)
        if not (b & 0x80):
            return n, i


def read_midi(path):
    """Return (ppqn, {channel(1-16): [(start_tick, end_tick, note, velocity)]})."""
    data = open(path, "rb").read()
    if data[:4] != b"MThd":
        raise ValueError(f"{path}: not a Standard MIDI File")
    _, fmt, ntrk, division = struct.unpack(">IHHH", data[4:14])
    if division & 0x8000:
        raise ValueError(f"{path}: SMPTE time division unsupported")
    ppqn = division
    notes = {}                       # channel -> list of completed (start,end,note,vel)
    pos = 14
    for _ in range(ntrk):
        if data[pos:pos + 4] != b"MTrk":
            raise ValueError(f"{path}: bad track chunk at {pos:#x}")
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        i, end = pos + 8, pos + 8 + length
        t = 0
        status = 0
        active = {}                  # (chan,note) -> (start_tick, vel)
        while i < end:
            dt, i = _read_vlq(data, i)
            t += dt
            b = data[i]
            if b & 0x80:
                status = b; i += 1
            # else running status: reuse previous status byte
            ev = status & 0xf0
            if ev in (0x80, 0x90, 0xa0, 0xb0, 0xe0):           # 2 data bytes
                d1, d2 = data[i], data[i + 1]; i += 2
                chan = (status & 0x0f) + 1
                if ev == 0x90 and d2 > 0:                       # note on
                    active[(chan, d1)] = (t, d2)
                elif ev == 0x80 or (ev == 0x90 and d2 == 0):    # note off
                    st = active.pop((chan, d1), None)
                    if st is not None:
                        notes.setdefault(chan, []).append((st[0], t, d1, st[1]))
            elif ev in (0xc0, 0xd0):                            # 1 data byte
                i += 1
            elif status == 0xff:                                # meta
                i += 1
                mlen, i = _read_vlq(data, i)
                i += mlen
            elif status in (0xf0, 0xf7):                        # sysex
                slen, i = _read_vlq(data, i)
                i += slen
            else:
                i += 1
        pos = end
    return ppqn, notes


# ── MIDI -> T-1 track field mapping ─────────────────────────────────────────────────
def _most_common(values, default):
    if not values:
        return default
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=lambda k: (counts[k], k == default))


def map_channel_to_track(channel_notes, ppqn, div, length):
    """Quantize one channel's notes to the step grid and derive T-1 track fields.
    Returns a kwargs dict for build_track_block, or None if no notes land on the grid."""
    grid = max(1, ppqn * 4 // div)               # MIDI ticks per step (matches playback division)
    t1_div = DIVISIONS[div]
    per_step = {}                                # step0 -> {'notes':set, 'vel':[], 'sus':[]}
    max_step = -1
    for start, end, note, vel in channel_notes:
        step = round(start / grid)
        if length:
            if step >= length:
                continue
        elif step >= 16:
            continue
        slot = per_step.setdefault(step, {"notes": [], "vel": [], "sus": []})
        slot["notes"].append(note)
        slot["vel"].append(vel)
        # note length -> sustain: dur(1 step)=sus 63; inverse of exporter's dur formula
        steps_long = (end - start) / grid
        slot["sus"].append(min(127, max(0, round(steps_long * 64) - 1)))
        max_step = max(max_step, step)
    if max_step < 0:
        return None
    steps = length or 16                          # full 16-step bar unless overridden

    gate = [0] * 16
    step_notes = {}                              # step0 -> sorted note list
    step_vel = {}
    step_sus = {}
    for step, slot in per_step.items():
        gate[step] = 1
        step_notes[step] = sorted(set(slot["notes"]))
        step_vel[step] = _most_common(slot["vel"], 100)
        step_sus[step] = _most_common(slot["sus"], 63)

    # Track default pitch is a SINGLE note here as a SAFE, device-verified CHOICE: chords/
    # polyphony and per-step pitch changes become per-step pitch LOCKS. NOTE: a multi-pitch
    # (chord) default IS valid on a stepped track too (see hwtest/fromT1/handmade2.zip), so this
    # is not a format requirement — just the encoding we verified. Prefer the most common
    # single-note step; if every active step is a chord, fall back to the most common root.
    singles = [n[0] for n in step_notes.values() if len(n) == 1]
    if singles:
        default_pitches = [_most_common(singles, 60)]
    else:
        default_pitches = [_most_common([min(n) for n in step_notes.values()], 60)]
    default_vel = _most_common(list(step_vel.values()), 100)
    default_sus = _most_common(list(step_sus.values()), 63)

    pitch_locks = {s: n for s, n in step_notes.items() if n != default_pitches}
    # Device drops a single-note-default track that is only PARTIALLY pitch-locked (a pulsed step
    # left playing the default while others are locked — hardware-confirmed). Device-authored
    # banks lock EITHER no steps or ALL active steps for such tracks (samples/11 block1,
    # handmade2 blk1). So once any lock is needed, lock every active step explicitly (same
    # playback, just no implicit-default pulses). Chord-default tracks tolerate partial locks
    # (handmade2 blk2), but locking all is always valid and keeps the rule simple.
    if pitch_locks:
        pitch_locks = dict(step_notes)
    groove_locks = {}
    for s in step_notes:
        gl = {}
        if step_vel[s] != default_vel:
            gl["velocity"] = step_vel[s]
        if step_sus[s] != default_sus:
            gl["sustain"] = step_sus[s]
        if gl:
            groove_locks[s] = gl

    return {
        "gate": gate, "pitches": default_pitches, "steps": steps,
        "division": t1_div, "scale": 0, "root": 0,
        "velocity": default_vel, "sustain": default_sus,
        "pitch_locks": pitch_locks, "groove_locks": groove_locks,
    }


def midi_to_pattern(path, template, div, length):
    ppqn, notes = read_midi(path)
    # collect all track fields first so the per-track count N is known before building blocks
    # (the lock-block end-marker at steps+0x2b6 is position-dependent: 1 for the first track,
    # else N-i; a wrong value makes the device drop that track).
    track_fields = []
    for chan in sorted(notes):                   # one track per channel, ascending
        if len(track_fields) >= 16:
            print(f"  warning: >16 channels in {path}; extra channels dropped")
            break
        fields = map_channel_to_track(notes[chan], ppqn, div, length)
        if fields is None:
            continue
        fields["mask"] = 1 << (chan - 1)
        track_fields.append(fields)
    n = len(track_fields)
    blocks = []
    last_has_locks = False
    for i, fields in enumerate(track_fields):
        end_mark = 1 if i == 0 else n - i
        last_has_locks = bool(fields["pitch_locks"] or fields["groove_locks"])
        blocks.append(build_track_block(template, end_mark=end_mark, **fields))
    return blocks, last_has_locks


# ── CLI ─────────────────────────────────────────────────────────────────────────────
def main(argv):
    args = argv[1:]
    out = None
    div = 16
    length = None
    template_path = DEFAULT_TEMPLATE
    inputs = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "--out"):
            out = args[i + 1]; i += 2
        elif a == "--div":
            div = int(args[i + 1]); i += 2
        elif a == "--length":
            length = int(args[i + 1]); i += 2
        elif a == "--template":
            template_path = args[i + 1]; i += 2
        elif a in ("-h", "--help"):
            print(__doc__); return 0
        elif a.startswith("-") and a not in ("-",):
            print(f"unknown option {a}"); return 1
        else:
            inputs.append(a); i += 1

    if not out or not inputs:
        print(__doc__); return 1
    if div not in DIVISIONS:
        print(f"--div must be one of {sorted(DIVISIONS)}"); return 1
    if length is not None and not (1 <= length <= 16):
        print("--length must be 1..16"); return 1

    template = load_template(template_path)
    patterns = []
    final_has_locks = False
    for path in inputs[:16]:
        blocks, last_has_locks = midi_to_pattern(path, template, div, length)
        if not blocks:
            print(f"  warning: {path} produced no tracks (no notes on grid)")
            continue
        patterns.append(blocks)
        final_has_locks = last_has_locks         # tracks the last serialized pattern's tail
        print(f"  {os.path.basename(path)} -> pattern {len(patterns)}: {len(blocks)} track(s)")
    if len(inputs) > 16:
        print(f"warning: only first 16 of {len(inputs)} inputs used (16 patterns max)")
    if not patterns:
        print("no patterns produced; nothing written"); return 1

    bank = build_bank(patterns, final_has_locks=final_has_locks)
    with open(out, "wb") as f:
        f.write(bank)
    print(f"wrote {out}  ({len(bank)} B, {len(patterns)} pattern(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
