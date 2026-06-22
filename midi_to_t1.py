#!/usr/bin/env python3
"""
midi_to_t1.py — import Standard MIDI File(s) into a Torso T-1 per-bank `.t1` backup.

Usage:
  midi_to_t1.py -o OUT.t1 IN1.mid [IN2.mid ...] [options]

Placement — pick how MIDI files map onto patterns/tracks of one bank:
  * default        each input `.mid` -> one pattern (slots 0,1,2,…); each MIDI channel (or SMF
                   track with --split-tracks) -> one track.
  * --by-filename  derive placement from names like `pattern1_track2.mid` (pattern# -> slot#-1,
                   track# orders tracks). Each file = one track (its merged notes).
  * --plan FILE    a JSON "table" giving exact backup/bank + per-pattern, per-track sources and
                   options (the most general; the midi-to-t1 skill emits this from an interview).
Notes are quantized to the step grid; chords/per-step pitch -> pitch locks; per-step velocity /
note-length -> groove locks (max 16 patterns x 16 tracks).

Output a device-loadable backup zip (the device restores a FULL backup, not a bank):
  * --zip BACKUP   splice the bank into a REAL backup (banks ≠slot + settings stay byte-identical)
  * --new-backup   build a fresh single-bank file (just `./` + `./<slot>.t1` — no other banks,
                   no Settings/Wifi). --slot N picks which bank (0..7) the content targets.

Options:
  -o, --out FILE     output .t1 (required)
  --div N            grid/playback division (1,2,4,8,16,32,64,3,6,12,24,48); default 16
  --length N         loop length in steps (1..16); default 16 (full bar). Single-cycle mode only.
  --split-tracks     map each SMF track (not each MIDI channel) to a T-1 track — so a chords
                     part and a bass part sharing one channel become two tracks.
  --cycles bars      distribute each voice's consecutive `--steps`-long windows across CYCLES
                     (window k -> cycle k). Omit for the legacy single-base-cycle behaviour.
  --steps N          steps per cycle/track, 1..64 (default 16). With `--cycles bars` this is the
                     window length that defines a cycle.
  --cycle-count N    force the cycle count 1..16 (default: auto = number of windows with notes).
  --by-filename      derive pattern/track placement from filenames (see Placement above).
  --plan FILE.json   assemble from an explicit placement table (see Placement; schema by run_plan).
  --zip BACKUP.zip   emit OUT.zip by splicing the bank into a real backup (non-destructive test).
  --new-backup       emit OUT.zip as a fresh backup from scratch (other banks empty).
  --slot N           which bank 0..7 the content fills (default 0); used by --zip/--new-backup/plan.
  --template FILE    .t1 whose first track block seeds the per-track "stored state"
                     region (default: samples/10_synth_test_import/0.t1)
  --bpm / ignored    tempo is a playback concern; the T-1 has its own clock.

Design: the format has no checksum (proven by on-device import). A track block contains a
large per-track "random sequence" region that is device-generated stored state; we clone it
from a known-good template block and patch in the fields we control, rebuilding the
variable-length pitch list and per-step lock lists. See FORMAT.md for the byte map.
"""
import math
import os
import re
import struct
import sys
import zipfile

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
SR_CYCLES = F.S_CYCLES                 # 0x14d: cycle count (1-16, default 4)
SR_STEPGROUP = F.S_STEPGROUP           # 0x2b0: step-group page selector (0-3)
GATE_LEN = F.GATE_LEN                  # 64: full gate array (steps 1-64)

PARAM_VELOCITY = 0x0a
PARAM_SUSTAIN = 0x0e
GROOVE_PARAM_CODE = {"velocity": PARAM_VELOCITY, "sustain": PARAM_SUSTAIN}

# ── Sustain law (hardware-confirmed) ─────────────────────────────────────────────────
# Note length is EXPONENTIAL in the stored byte: it DOUBLES every 16 byte units (every 2 of
# the device's 16 LED steps), anchored at byte 64 = 50% = "one full division" (1 step).
#   length_steps = 2**((byte-64)/16)        byte = 64 + 16*log2(length_steps)
# Confirmed on device: 8/16 LED(byte 64)=1 step, 12/16(96)=4, 14/16(112)=8, 16/16(127)=16.
SUSTAIN_DEFAULT = 64                          # one full division (device default, 50%)


def sustain_byte(steps_long):
    """Note length (in steps/divisions) -> stored sustain byte, per the device's log law."""
    if steps_long <= 0:
        return 0
    return max(0, min(127, round(64 + 16 * math.log2(steps_long))))


def sustain_steps(sus_byte):
    """Stored sustain byte -> note length in steps/divisions (inverse of sustain_byte)."""
    return 2.0 ** ((sus_byte - 64) / 16)

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


# ── lock-list serialization (shared by base track AND per-cycle records) ──────────────
def _groove_bytes(groove_locks):
    """Serialize a groove-lock list. `groove_locks` = {step0: {'velocity'|'sustain': value}}
    or {step0: {param_id:int: value}} (raw). Newest/step-desc first; one record per step packs
    all its params: [entry_count][step] then N*[param][value:u16 LE][00 00]."""
    out = bytearray([len(groove_locks)])
    for step, gl in sorted(groove_locks.items(), reverse=True):
        out += bytes([len(gl), step])
        for name, value in gl.items():
            pid = name if isinstance(name, int) else GROOVE_PARAM_CODE[name]
            out += bytes([pid]) + struct.pack("<H", value) + b"\x00\x00"
    return bytes(out)


def _pitch_bytes(pitch_locks):
    """Serialize a pitch-lock list: [count] then per step-desc [step][count:u32 LE][notes]."""
    out = bytearray([len(pitch_locks)])
    for step, notes in sorted(pitch_locks.items(), reverse=True):
        out += bytes([step]) + struct.pack("<I", len(notes)) + bytes(notes)
    return bytes(out)


# ── track block synthesis ───────────────────────────────────────────────────────────
def build_track_block(template, *, gate, pitches, steps, division, scale, root,
                      velocity, sustain, mask, pitch_locks, groove_locks, end_mark=1,
                      cycles=4, step_group=0, cycle_pitch=None, cycle_records=None,
                      cycle_params=None):
    """Synthesize one 803+ byte track block by cloning `template` stored-state and
    patching the controllable fields + variable-length pitch/lock/cycle regions.

    gate          : iterable of up to 64 ints (0/1) — full step range
    pitches       : track-default pitch list (>=1 absolute notes, C3=60)
    pitch_locks   : {step0: [notes]}      base per-step pitch overrides (incl. chords)
    groove_locks  : {step0: {'velocity'|'sustain': value}}  base per-step groove overrides
    cycles        : cycle count 1-16 (default 4)
    step_group    : step-group page selector 0-3 (UI cursor)
    cycle_pitch   : [(cyc_idx, [notes]), ...] per-cycle TRACK-pitch overrides (stored order)
    cycle_records : [(cyc_idx, gate64, groove_locks, pitch_locks), ...] per-cycle step-seq records
    cycle_params  : [(cyc_idx, [(param_id, value), ...]), ...] per-cycle TRACK-param overrides
    See FORMAT.md "STEPS up to 64 + CYCLES". Defaults reproduce a plain (no-cycle) block exactly.
    """
    _, steps_region = template
    gate = list(gate)[:GATE_LEN] + [0] * max(0, GATE_LEN - len(gate))
    cycle_pitch = list(cycle_pitch or [])
    cycle_records = list(cycle_records or [])
    cycle_params = list(cycle_params or [])

    b = bytearray()
    b += b"\x0c\x00" + bytes([len(pitches)]) + b"\x00\x00\x00"   # block marker + pitch count
    b += bytes(pitches)                                          # base pitch list (variable)
    b += bytes([len(cycle_pitch)])                              # per-cycle pitch override count
    for cyc, notes in cycle_pitch:                              # [cyc_idx][count:u32][notes]
        b += bytes([cyc]) + struct.pack("<I", len(notes)) + bytes(notes)
    b += b"\x0c\x00\x00\x00"                                     # post-pitch separator
    b += RUN                                                     # 00..0b landmark
    b += bytes(gate)                                             # 64-byte gate array

    # lock region: base groove + pitch lists, then per-cycle step-seq records, then per-cycle
    # track-param overrides, then a 16-byte pad (see FORMAT.md). With no cycles this is exactly
    # the historical `[groove][pitch] + 18 zero pad` (num_edited=0, param_num=0, 16 zeros).
    b += _groove_bytes(groove_locks)
    b += _pitch_bytes(pitch_locks)
    b += bytes([len(cycle_records)])                            # num_edited_cycles
    for cyc, cgate, cgroove, cpitch in cycle_records:
        cgate = list(cgate)[:GATE_LEN] + [0] * max(0, GATE_LEN - len(cgate))
        b += bytes([cyc]) + bytes(cgate) + _groove_bytes(cgroove) + _pitch_bytes(cpitch)
    b += bytes([len(cycle_params)])                            # param-override record count
    for cyc, entries in cycle_params:                          # [entry_count][cyc] + 5B entries
        b += bytes([len(entries), cyc])
        for pid, value in entries:
            b += bytes([pid]) + struct.pack("<H", value) + b"\x00\x00"
    b += b"\x00" * 16

    # steps region: clone template, patch documented fields
    sr = bytearray(steps_region)
    sr[SR_STEPS] = steps
    struct.pack_into("<H", sr, SR_DIVISION, division)
    sr[SR_SCALE] = scale
    sr[SR_VELOCITY] = velocity
    sr[SR_SUSTAIN] = sustain
    struct.pack_into("<H", sr, SR_MIDIMASK, mask)
    sr[SR_ROOT] = root
    sr[SR_CYCLES] = cycles
    sr[SR_STEPGROUP] = step_group
    # locks live in the base track OR any per-cycle record; both set the lock-summary/terminator.
    cyc_locks = any(g or p for _, _, g, p in cycle_records)
    has_locks = bool(pitch_locks or groove_locks or cyc_locks)
    # Position end-marker (device drops a track whose value is wrong): `end_mark` = i+1 for every
    # track except the pattern's last (1). It lives at steps+0x2b5 on a NON-lock block (2b6=0) and
    # at steps+0x2b6 on a LOCK block (2b5=0) — set it for BOTH kinds (the non-lock case was the
    # bug that dropped every position-2+ non-lock track). Self-templated rebuilds pass the block's
    # own extracted value, so this stays byte-exact.
    if has_locks:
        sr[SR_END_MARK] = 0; sr[SR_END_MARK + 1] = end_mark
    else:
        sr[SR_END_MARK] = end_mark; sr[SR_END_MARK + 1] = 0
    # If the block carries locks but the template's steps-region is a NON-lock one (its lock
    # summary is absent), synthesize the trailing lock-summary the device requires; otherwise a
    # lock-bearing block cloned from a non-lock template mis-renders (chords) and drops a later
    # pattern. Skipped when the template already has the summary (e.g. self-templated roundtrip).
    if has_locks and sr[SR_LOCK_FLAG] == 0:
        locked_steps = set(pitch_locks) | set(groove_locks)
        for _, _, g, p in cycle_records:
            locked_steps |= set(g) | set(p)
        sr[SR_LOCK_FLAG] = 1
        struct.pack_into("<H", sr, SR_LOCK_CURSOR, max(locked_steps) if locked_steps else 0)
    b += sr
    if has_locks:
        b += b"\x00"                               # lock terminator byte (see FORMAT.md)
    return bytes(b)


# ── bank (container) synthesis ──────────────────────────────────────────────────────
def build_bank(patterns, current_pattern=0, indices=None, final_has_locks=False,
               track_cursors=None):
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
    # `track_cursors` = the per-pattern saved "current track" cursor (0-based) that goes in each
    # pattern's end-trailer (offset +2). UI state — the track the device opens that pattern on;
    # CAN exceed the serialized track count (e.g. cursor parked on an empty track). Defaults to
    # the last serialized track. (This byte was historically read as `prev_tc-1`; that held only
    # because the cursor sat on the last track. See FORMAT.md.)
    if track_cursors is None:
        track_cursors = [len(p) - 1 for p in patterns]
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
        out += bytes([0, 0, track_cursors[i - 1], 0, 0, 0, 0, 0])  # end-of-prev-pattern trailer
        out += bytes([indices[i], len(patterns[i]), 0, 0])      # next-pattern header (slot, tc)
        out += b"".join(patterns[i])
    out += bytes([0, 0, track_cursors[-1], 0, 0, 0, 0, 0])      # end-of-last-pattern trailer
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


def read_midi_tracks(path):
    """Parse an SMF split by SMF TRACK (not merged by MIDI channel). Returns
    (ppqn, [(name, [(start,end,note,vel,chan), ...]), ...]) for every track carrying notes,
    capturing the track-name meta (0xFF 0x03). Used by --split-tracks so e.g. a chords part and
    a bass part sharing one channel become two T-1 tracks."""
    data = open(path, "rb").read()
    if data[:4] != b"MThd":
        raise ValueError(f"{path}: not a Standard MIDI File")
    _, _fmt, ntrk, division = struct.unpack(">IHHH", data[4:14])
    if division & 0x8000:
        raise ValueError(f"{path}: SMPTE time division unsupported")
    ppqn = division
    tracks = []
    pos = 14
    for _ in range(ntrk):
        if data[pos:pos + 4] != b"MTrk":
            raise ValueError(f"{path}: bad track chunk at {pos:#x}")
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        i, end = pos + 8, pos + 8 + length
        t = 0; status = 0; active = {}; notes = []; name = None
        while i < end:
            dt, i = _read_vlq(data, i); t += dt
            b = data[i]
            if b & 0x80:
                status = b; i += 1
            ev = status & 0xf0
            if ev in (0x80, 0x90, 0xa0, 0xb0, 0xe0):
                d1, d2 = data[i], data[i + 1]; i += 2
                chan = (status & 0x0f) + 1
                if ev == 0x90 and d2 > 0:
                    active[(chan, d1)] = (t, d2)
                elif ev == 0x80 or (ev == 0x90 and d2 == 0):
                    st = active.pop((chan, d1), None)
                    if st is not None:
                        notes.append((st[0], t, d1, st[1], chan))
            elif ev in (0xc0, 0xd0):
                i += 1
            elif status == 0xff:
                mtype = data[i]; i += 1
                mlen, i = _read_vlq(data, i)
                if mtype == 0x03:
                    name = data[i:i + mlen].decode("latin1", "replace")
                i += mlen
            elif status in (0xf0, 0xf7):
                slen, i = _read_vlq(data, i); i += slen
            else:
                i += 1
        if notes:
            tracks.append((name, notes))
        pos = end
    return ppqn, tracks


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
        # note length -> sustain via the device's log law (see sustain_byte): 1 step -> 64,
        # 4 steps -> 96, 8 -> 112, 16 -> ~127. Inverse of exporter's 2**((sus-64)/16).
        steps_long = (end - start) / grid
        slot["sus"].append(sustain_byte(steps_long))
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
        step_sus[step] = _most_common(slot["sus"], 64)   # 64 = one full division (device default)

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
    default_sus = _most_common(list(step_sus.values()), 64)

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


# ── MIDI -> T-1 CYCLES mapping (bars -> cycles) ───────────────────────────────────────
def _quantize_window(window_notes, grid, steps):
    """Quantize one cycle window's notes to a `steps`-long grid. `window_notes` =
    [(rel_start, rel_end, note, vel), ...] (ticks relative to the window start). Returns
    {step0: {'notes':[sorted], 'vel':v, 'sus':byte}}."""
    per = {}
    for rs, re, note, vel in window_notes:
        step = round(rs / grid)
        if step >= steps:
            continue
        slot = per.setdefault(step, {"notes": [], "vel": [], "sus": []})
        slot["notes"].append(note)
        slot["vel"].append(vel)
        slot["sus"].append(sustain_byte((re - rs) / grid))
    return {s: {"notes": sorted(set(v["notes"])),
                "vel": _most_common(v["vel"], 100),
                "sus": _most_common(v["sus"], SUSTAIN_DEFAULT)}
            for s, v in per.items()}


def build_cycle_track(voice_notes, ppqn, div, steps, cycle_count=None):
    """Map one voice's notes onto a CYCLES-based track: each consecutive `steps`-long window
    becomes one cycle (window k -> cycle k). Returns build_track_block kwargs (minus mask/
    end_mark). `voice_notes` = [(start,end,note,vel[,chan]), ...] absolute ticks. `cycle_count`
    overrides the auto count (= number of windows that contain notes), clamped 1..16.

    ENCODING (the device's own NATURAL form, hardware-verified incl. byte-exact rebuild of a
    device-authored base-locks+records bank, samples/17): base track = cycle 0 WITH its per-step
    pitch (incl. chords) + groove (velocity/sustain) locks; a per-cycle step-seq record is emitted
    ONLY for cycles whose content differs from cycle 0 (an identical cycle just replays the base —
    e.g. a repeated bar needs no record). Every active step is pitch-locked so the single-note
    default never sounds (avoids the partial-lock drop rule)."""
    grid = max(1, ppqn * 4 // div)
    window = steps * grid
    buckets = {}
    max_cyc = -1
    for note in voice_notes:
        start, end, n, vel = note[0], note[1], note[2], note[3]
        cyc = start // window
        buckets.setdefault(cyc, []).append((start - cyc * window, end - cyc * window, n, vel))
        max_cyc = max(max_cyc, cyc)
    ncyc = cycle_count if cycle_count else (max_cyc + 1)
    ncyc = max(1, min(16, ncyc))
    quant = {c: _quantize_window(buckets.get(c, []), grid, steps) for c in range(ncyc)}

    cells = [st for q in quant.values() for st in q.values()]
    singles = [st["notes"][0] for st in cells if len(st["notes"]) == 1]
    if singles:
        default_pitch = _most_common(singles, 60)
    else:
        default_pitch = _most_common([min(st["notes"]) for st in cells], 60)
    default_vel = _most_common([st["vel"] for st in cells], 100)
    default_sus = _most_common([st["sus"] for st in cells], SUSTAIN_DEFAULT)

    def to_cycle(q):
        gate = [0] * GATE_LEN
        pitch_locks, groove_locks = {}, {}
        for step, st in q.items():
            gate[step] = 1
            pitch_locks[step] = st["notes"]          # lock every active step (covers chords)
            gl = {}
            if st["vel"] != default_vel:
                gl[PARAM_VELOCITY] = st["vel"]
            if st["sus"] != default_sus:
                gl[PARAM_SUSTAIN] = st["sus"]
            if gl:
                groove_locks[step] = gl
        return gate, groove_locks, pitch_locks

    base_gate, base_groove, base_pitch = to_cycle(quant[0])   # cycle 0 = base (carries its locks)
    cycle_records = []
    for c in range(ncyc - 1, 0, -1):                 # descending; cycle 0 is the base, skip it
        g, gr, pl = to_cycle(quant[c])
        if (g, gr, pl) == (base_gate, base_groove, base_pitch):
            continue                                 # identical to base -> replays it, no record
        cycle_records.append((c, g, gr, pl))

    return {
        "gate": base_gate, "pitches": [default_pitch], "steps": steps,
        "division": DIVISIONS[div], "scale": 0, "root": 0,
        "velocity": default_vel, "sustain": default_sus,
        "pitch_locks": base_pitch, "groove_locks": base_groove,
        "cycles": ncyc, "step_group": 0, "cycle_pitch": [],
        "cycle_records": cycle_records, "cycle_params": [],
    }


def _voices(path, split):
    """Return (ppqn, [(label, notes_with_chan), ...]). split=True -> one voice per SMF track;
    else one voice per MIDI channel (legacy)."""
    if split:
        ppqn, smf = read_midi_tracks(path)
        return ppqn, [(name or f"track{i + 1}", notes) for i, (name, notes) in enumerate(smf)]
    ppqn, by_chan = read_midi(path)
    return ppqn, [(f"ch{ch}", [(s, e, n, v, ch) for (s, e, n, v) in by_chan[ch]])
                  for ch in sorted(by_chan)]


def _voice_to_kwargs(notes, ppqn, div, length, cycles_mode, steps, cycle_count, channel=None):
    """One voice's notes (with per-note channel) -> build_track_block kwargs (incl. mask), or
    None if no notes land on the grid. `channel` forces the output MIDI channel (else inferred)."""
    chan = channel or (_most_common([nt[4] for nt in notes], 1) if notes else 1)
    if cycles_mode == "bars":
        kw = build_cycle_track(notes, ppqn, div, steps, cycle_count)
    else:
        kw = map_channel_to_track([nt[:4] for nt in notes], ppqn, div, length)
        if kw is None:
            return None
    kw["mask"] = 1 << (chan - 1)
    return kw


def _blocks_from_kwargs(template, kwargs_list):
    """Build a pattern's track blocks from per-track kwargs, assigning the position-dependent
    end-marker. Returns (blocks, last_block_has_locks)."""
    n = len(kwargs_list)
    blocks, last_has_locks = [], False
    for i, kw in enumerate(kwargs_list):
        # lock-block end-marker (steps+0x2b6): i+1 for every track except the pattern's LAST (1).
        end_mark = 1 if i == n - 1 else i + 1
        last_has_locks = bool(kw["pitch_locks"] or kw["groove_locks"]
                              or any(g or p for _, _, g, p in kw.get("cycle_records", [])))
        blocks.append(build_track_block(template, end_mark=end_mark, **kw))
    return blocks, last_has_locks


def midi_to_pattern(path, template, div, length, *, split=False, cycles_mode=None,
                    steps=16, cycle_count=None):
    """One `.mid` -> one pattern (list of track blocks). `split` maps SMF tracks (not channels)
    to T-1 tracks. `cycles_mode='bars'` distributes each voice's `steps`-long windows across
    cycles; otherwise a single base cycle (legacy). Returns (blocks, last_block_has_locks)."""
    ppqn, voices = _voices(path, split)
    kwargs_list = []
    for label, notes in voices:
        if len(kwargs_list) >= 16:
            print(f"  warning: >16 voices in {path}; extras dropped")
            break
        kw = _voice_to_kwargs(notes, ppqn, div, length, cycles_mode, steps, cycle_count)
        if kw is not None:
            kwargs_list.append(kw)
    return _blocks_from_kwargs(template, kwargs_list)


# ── backup-zip output (fold the splice recipe into the importer) ──────────────────────
_BACKUP_NAMES = ["./", "./0.t1", "./1.t1", "./2.t1", "./3.t1", "./4.t1", "./5.t1", "./6.t1",
                 "./7.t1", "./Settings.json", "./Wifi.json"]


def write_backup_zip(bank_bytes, out_zip, slot=0, src_zip=None):
    """Emit a device-loadable zip with `bank_bytes` as bank `slot` (0..7). Two layouts:

      * src_zip given  -> FULL-backup splice: keep all 8 banks + Settings/Wifi from a REAL backup,
        replacing only `slot` (other entries stay byte-identical — verified). Restoring overwrites
        all 8 banks, so this is the non-destructive way to test (banks ≠slot are preserved as-is).
      * src_zip None   -> FRESH single-bank file: just `./` + `./<slot>.t1` — NO empty banks, NO
        Settings.json, NO Wifi.json. Minimal; only the one bank the user wants.

    Always ZIP_STORED, ./-prefixed."""
    dt = (1980, 1, 1, 0, 0, 0)
    if src_zip is not None:
        src = zipfile.ZipFile(src_zip)
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_STORED) as z:
            for nm in _BACKUP_NAMES:
                zi = zipfile.ZipInfo(nm, date_time=dt); zi.compress_type = zipfile.ZIP_STORED
                if nm == "./":
                    zi.external_attr = (0o40755 << 16) | 0x10; z.writestr(zi, b""); continue
                data = bank_bytes if nm == f"./{slot}.t1" else src.read(nm)
                zi.external_attr = 0o644 << 16; z.writestr(zi, data)
        out = zipfile.ZipFile(out_zip)                # verify untouched entries are byte-identical
        for nm in _BACKUP_NAMES:
            if nm in ("./", f"./{slot}.t1"):
                continue
            if src.read(nm) != out.read(nm):
                raise ValueError(f"{nm} changed during splice — aborting")
        return
    # fresh single-bank file: directory entry + the one bank only
    entries = [("./", None), (f"./{slot}.t1", bank_bytes)]
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_STORED) as z:
        for nm, data in entries:
            zi = zipfile.ZipInfo(nm, date_time=dt); zi.compress_type = zipfile.ZIP_STORED
            if data is None:
                zi.external_attr = 0x10; z.writestr(zi, b"")          # directory entry
            else:
                zi.external_attr = 0x00000000; z.writestr(zi, data)


# ── placement plan: which MIDI/voice -> which pattern/track (the "table") ─────────────
# A plan is a dict:
#   {"backup": "new"|"<real_backup.zip>", "bank": 0..7, "div": 16,
#    "patterns": [ {"slot": 0..15, "tracks": [ TRACKSPEC, ... ]}, ... ]}
# TRACKSPEC = {"midi": path, "track": 1.., (one source selector:) "smf_track": idx | "name": str |
#   "channel": 1..16, (per-track opts, all optional:) "cycles": "bars", "steps": 1..64,
#   "cycle_count": 1..16, "div": N, "length": 1..16, "out_channel": 1..16}
# Front-ends below build this dict; run_plan() turns it into bank bytes. The FIRST serialized
# pattern is device slot 0 (container limitation); higher `slot`s may be sparse.

def _select_voice(smf_tracks, spec):
    """smf_tracks = [(name, notes), ...] from read_midi_tracks. Pick this track's source notes by
    'smf_track' index, 'name' (case-insensitive substring), or 'channel'; default = all merged."""
    if spec.get("smf_track") is not None:
        return smf_tracks[spec["smf_track"]][1]
    if spec.get("name"):
        for nm, notes in smf_tracks:
            if nm and spec["name"].lower() in nm.lower():
                return notes
        raise ValueError(f"no SMF track name matches {spec['name']!r} in plan")
    if spec.get("channel") is not None:
        return [n for _, notes in smf_tracks for n in notes if n[4] == spec["channel"]]
    return [n for _, notes in smf_tracks for n in notes]


def run_plan(plan, template):
    """Assemble bank bytes from a placement plan. Returns (bank_bytes, bank_slot, backup_src)
    where backup_src is None for a from-scratch backup or a path to splice into."""
    div_default = plan.get("div", 16)
    cache = {}
    def voices_of(path):
        if path not in cache:
            cache[path] = read_midi_tracks(path)
        return cache[path]
    patterns_blocks, indices = [], []
    final_has_locks = False
    for pat in sorted(plan["patterns"], key=lambda p: p.get("slot", 0)):
        kwargs_list = []
        for ts in sorted(pat["tracks"], key=lambda t: t.get("track", 0)):
            ppqn, smf = voices_of(ts["midi"])
            notes = _select_voice(smf, ts)
            kw = _voice_to_kwargs(notes, ppqn, ts.get("div", div_default), ts.get("length"),
                                  ts.get("cycles"), ts.get("steps", 16), ts.get("cycle_count"),
                                  channel=ts.get("out_channel"))
            if kw is not None:
                kwargs_list.append(kw)
        if not kwargs_list:
            continue
        blocks, last = _blocks_from_kwargs(template, kwargs_list)
        patterns_blocks.append(blocks)
        indices.append(pat.get("slot", len(patterns_blocks) - 1))
        final_has_locks = last
    if not patterns_blocks:
        raise ValueError("plan produced no patterns (no notes on grid?)")
    if indices and indices[0] != 0:
        print(f"  note: first serialized pattern is device slot 0 (requested {indices[0]}); "
              "lower slots can't be left empty by the container")
        indices[0] = 0
    bank = build_bank(patterns_blocks, indices=indices, final_has_locks=final_has_locks)
    backup = plan.get("backup", "new")
    return bank, plan.get("bank", 0), (None if backup in (None, "new") else backup)


_PAT_RE = re.compile(r"pattern[_-]?(\d+)", re.I)
_TRK_RE = re.compile(r"track[_-]?(\d+)", re.I)


def plan_from_filenames(inputs, *, bank, backup, cycles_mode, steps, cycle_count, div, length):
    """Derive a plan from filenames like `pattern1_track2.mid` (1-based pattern# -> slot pattern#-1;
    track# orders tracks within the pattern). Missing `patternN` -> pattern 1; missing `trackN` ->
    next free track in that pattern. Each file = ONE track sourced from its merged notes."""
    by_pat, auto = {}, {}
    for path in inputs:
        base = os.path.basename(path)
        pm, tm = _PAT_RE.search(base), _TRK_RE.search(base)
        p = int(pm.group(1)) if pm else 1
        if tm:
            t = int(tm.group(1))
        else:
            auto[p] = auto.get(p, 0) + 1; t = auto[p]
        by_pat.setdefault(p, []).append({
            "midi": path, "track": t, "cycles": cycles_mode, "steps": steps,
            "cycle_count": cycle_count, "div": div, "length": length})
    patterns = [{"slot": p - 1, "tracks": tracks} for p, tracks in sorted(by_pat.items())]
    return {"backup": backup, "bank": bank, "div": div, "patterns": patterns}


def plan_per_file(inputs, *, bank, backup, split, cycles_mode, steps, cycle_count, div, length):
    """Default front-end: each input `.mid` -> one pattern (contiguous slots from 0); within it,
    each SMF track (split) or MIDI channel -> one track."""
    patterns = []
    for i, path in enumerate(inputs):
        _ppqn, voices = _voices(path, split)
        tracks = []
        for vi, (_label, notes) in enumerate(voices):
            chan = _most_common([n[4] for n in notes], 1) if notes else 1
            tracks.append({
                "midi": path, "track": vi + 1,
                "smf_track": vi if split else None,
                "channel": None if split else chan,
                "cycles": cycles_mode, "steps": steps, "cycle_count": cycle_count,
                "div": div, "length": length})
        patterns.append({"slot": i, "tracks": tracks})
    return {"backup": backup, "bank": bank, "div": div, "patterns": patterns}


# ── CLI ─────────────────────────────────────────────────────────────────────────────
def main(argv):
    args = argv[1:]
    out = None
    div = 16
    length = None
    template_path = DEFAULT_TEMPLATE
    split = False
    cycles_mode = None          # None (single base cycle) | 'bars'
    steps = 16
    cycle_count = None          # None = auto (one cycle per window with notes)
    zip_src = None
    new_backup = False
    by_filename = False
    plan_path = None
    slot = 0
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
        elif a == "--split-tracks":
            split = True; i += 1
        elif a == "--cycles":
            cycles_mode = args[i + 1]; i += 2
        elif a == "--steps":
            steps = int(args[i + 1]); i += 2
        elif a == "--cycle-count":
            cycle_count = int(args[i + 1]); i += 2
        elif a == "--zip":
            zip_src = args[i + 1]; i += 2
        elif a == "--new-backup":
            new_backup = True; i += 1
        elif a == "--by-filename":
            by_filename = True; i += 1
        elif a == "--plan":
            plan_path = args[i + 1]; i += 2
        elif a == "--slot":
            slot = int(args[i + 1]); i += 2
        elif a in ("-h", "--help"):
            print(__doc__); return 0
        elif a.startswith("-") and a not in ("-",):
            print(f"unknown option {a}"); return 1
        else:
            inputs.append(a); i += 1

    if not out or (not inputs and not plan_path):
        print(__doc__); return 1
    if div not in DIVISIONS:
        print(f"--div must be one of {sorted(DIVISIONS)}"); return 1
    if length is not None and not (1 <= length <= 16):
        print("--length must be 1..16"); return 1
    if cycles_mode not in (None, "bars"):
        print("--cycles must be 'bars' (or omitted)"); return 1
    if not (1 <= steps <= 64):
        print("--steps must be 1..64"); return 1
    if cycle_count is not None and not (1 <= cycle_count <= 16):
        print("--cycle-count must be 1..16"); return 1
    if not (0 <= slot <= 7):
        print("--slot must be 0..7"); return 1
    if zip_src and new_backup:
        print("use either --zip (splice into a real backup) or --new-backup, not both"); return 1

    template = load_template(template_path)

    # Build the placement plan from whichever front-end is selected, then assemble.
    backup = zip_src if zip_src else ("new" if new_backup else None)
    if plan_path:
        import json
        plan = json.load(open(plan_path))
        plan.setdefault("bank", slot)
        if backup is not None:
            plan["backup"] = backup          # CLI overrides plan's backup choice
    elif by_filename:
        plan = plan_from_filenames(inputs, bank=slot, backup=backup, cycles_mode=cycles_mode,
                                   steps=steps, cycle_count=cycle_count, div=div, length=length)
    else:
        plan = plan_per_file(inputs[:16], bank=slot, backup=backup, split=split,
                             cycles_mode=cycles_mode, steps=steps, cycle_count=cycle_count,
                             div=div, length=length)

    bank, bank_slot, backup_src = run_plan(plan, template)
    with open(out, "wb") as f:
        f.write(bank)
    npat = len(plan["patterns"])
    print(f"wrote {out}  ({len(bank)} B, {npat} pattern(s), bank slot {bank_slot})")

    # Emit a loadable backup zip whenever a backup target is set (CLI --zip/--new-backup, or the
    # plan's "backup" field). plan.get("backup")=="new" / None -> from scratch; else splice.
    if plan.get("backup") is not None:
        zip_out = os.path.splitext(out)[0] + ".zip"
        write_backup_zip(bank, zip_out, slot=bank_slot, src_zip=backup_src)
        where = "fresh single-bank project export" if backup_src is None \
            else f"spliced into {os.path.basename(backup_src)}"
        print(f"wrote {zip_out}  (bank slot {bank_slot}, {where})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
