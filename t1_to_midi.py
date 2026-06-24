#!/usr/bin/env python3
"""
t1_to_midi.py — export a Torso T-1 per-bank `.t1` backup to Standard MIDI File(s).

Usage:
  t1_to_midi.py FILE.t1 [-o OUTDIR] [--bpm 120] [--step 1/16]

Writes one .mid per non-empty pattern (Type 1: one MIDI track per T-1 track).
Dependency-free SMF writer.

Decoded fields used: gate array, steps, per-track division, pitches (absolute, C3=60), per-step
pitch/velocity/sustain locks, MIDI channel mask, bank Tempo (->BPM), track Length (->loop end),
and Timing/Delay (->note onset shifts). See FORMAT.md.

Approximations (see FORMAT.md "Still open" / "Backup-1 decode"):
  * note length derived from `sustain` via the device log law.
  * Timing/Delay applied with a PROVISIONAL 1 unit ≈ 1 tick scale (real units TBD — follow-up).
  * scale/root quantization not applied (exports the stored absolute pitch).
  * --bpm overrides the bank's stored Tempo.
"""
import struct
import sys
import os

import t1_format

TPQN = t1_format.PPQN   # 96, matches the T-1 internal resolution (division in ticks)
BAR_TICKS = TPQN * 4    # one 4/4 bar in ticks (Length is in bars; see length_to_ticks)

# PROVISIONAL: the exact tick scale of Timing (swing) and Delay (track shift) is a pending
# follow-up — backup-1 located the signed fields but not their real-world units. Until a dedicated
# sweep pins it, treat 1 stored unit ≈ 1 tick @96 PPQN. Both default to 0 (no shift), so this is a
# no-op for any track that doesn't use them (existing exports are unchanged).
TIMING_TICKS_PER_UNIT = 1
DELAY_TICKS_PER_UNIT = 1


def length_to_ticks(length_enum, step_count, step_ticks):
    """Track loop length in ticks from the Length enum (backup-1). Infinite (or unknown) falls back
    to the natural step span (step_count * step_ticks)."""
    bars = t1_format.LENGTH_BARS.get(length_enum)
    if bars is None:
        return step_count * step_ticks
    return max(1, round(bars * BAR_TICKS))


def _sustain_steps(sus_byte):
    """Stored sustain byte -> note length in step divisions (device's log law): length
    DOUBLES every 16 byte units, anchored at byte 64 = one division. Hardware-confirmed
    (8/16 LED byte 64=1 step, 12/16=96=4, 14/16=112=8, 16/16=127≈16). See midi_to_t1.sustain_byte."""
    return 2.0 ** ((sus_byte - 64) / 16)


def _vlq(n):
    out = bytearray([n & 0x7f])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7f) | 0x80)
        n >>= 7
    return bytes(out)


def _note_to_midi(p):
    while p > 127:
        p -= 12
    while p < 0:
        p += 12
    return p


def build_smf(patterns, bpm):
    def meta_track():
        ev = bytearray()
        ev += _vlq(0) + bytes([0xFF, 0x51, 0x03]) + struct.pack(">I", int(60_000_000 / bpm))[1:]
        ev += _vlq(0) + bytes([0xFF, 0x2F, 0x00])
        return bytes(ev)

    tracks_out = [meta_track()]

    for pi, pattern in patterns:
        for ti, t in enumerate(pattern):
            chans = t["midi_channels"]
            if not chans or not t["pitches"]:
                continue
            step_count = t["steps"] or 16
            step_ticks = t["division_ticks"] or 24
            # Timing (swing) shifts every 2nd step; Delay shifts the whole track. Units provisional
            # (see TIMING_TICKS_PER_UNIT); both 0 by default -> no change. (backup-1)
            delay_off = t.get("delay", 0) * DELAY_TICKS_PER_UNIT
            swing_off = t.get("timing", 0) * TIMING_TICKS_PER_UNIT
            # collect (tick, on/off, chan, note, vel) — applying per-step overrides
            events = []
            for s in range(step_count):
                if s < 16 and t["gate"][s]:
                    on = s * step_ticks + delay_off + (swing_off if s % 2 else 0)
                    on = max(0, on)
                    notes = t["pitch_locks"].get(s, t["pitches"])
                    gl = t["groove_locks"].get(s, {})
                    vel = gl.get("velocity", t["velocity"])
                    sus = gl.get("sustain", t["sustain"])
                    # Sustain -> note length via the device's log law: byte 64 = one division;
                    # length doubles every 16 byte units (see _sustain_steps / groove/sustain page).
                    dur = max(1, round(step_ticks * _sustain_steps(sus)))
                    for note in notes:
                        m = _note_to_midi(note)
                        for ch in chans:
                            events.append((on, 1, ch - 1, m, vel))
                            events.append((on + dur, 0, ch - 1, m, 0))
            events.sort(key=lambda e: (e[0], e[1]))  # offs before ons at same tick
            ev = bytearray()
            ev += _vlq(0) + bytes([0xFF, 0x03]) + _vlq(len(f"P{pi+1}T{ti+1}")) + f"P{pi+1}T{ti+1}".encode()
            last = 0
            for tick, kind, ch, note, vel in events:
                ev += _vlq(tick - last)
                ev += bytes([(0x90 if kind else 0x80) | (ch & 0x0f), note, vel])
                last = tick
            # loop end marker — use the track's Length (loop length in bars), falling back to the
            # natural step span when infinite/unset (backup-1).
            loop_ticks = length_to_ticks(t.get("length", 0), step_count, step_ticks)
            ev += _vlq(max(0, loop_ticks - last))
            ev += bytes([0xFF, 0x2F, 0x00])
            tracks_out.append(bytes(ev))

    body = struct.pack(">4sIHHH", b"MThd", 6, 1, len(tracks_out), TPQN)
    for tr in tracks_out:
        body += struct.pack(">4sI", b"MTrk", len(tr)) + tr
    return body


def main(argv):
    args = argv[1:]
    if not args:
        print(__doc__); return 1
    path = args[0]
    outdir = "."
    bpm = None
    i = 1
    while i < len(args):
        if args[i] == "-o":
            outdir = args[i + 1]; i += 2
        elif args[i] == "--bpm":
            bpm = float(args[i + 1]); i += 2
        else:
            i += 1
    bank = t1_format.parse_bank(path)
    if bpm is None:                       # default to the bank's stored Tempo (backup-1); --bpm wins
        bpm = bank["tempo"] or 120.0
    # one .mid per pattern that has any playable track
    base = os.path.splitext(os.path.basename(path))[0]
    os.makedirs(outdir, exist_ok=True)
    written = 0
    for pi, pattern in enumerate(bank["patterns"]):
        playable = [t for t in pattern if t["midi_channels"] and t["pitches"]
                    and any(t["gate"])]
        if not playable:
            continue
        smf = build_smf([(pi, pattern)], bpm)
        out = os.path.join(outdir, f"{base}_pattern{pi+1}.mid")
        with open(out, "wb") as f:
            f.write(smf)
        print(f"wrote {out}  ({len(pattern)} tracks, {len(playable)} playable)")
        written += 1
    if not written:
        print("no playable patterns found")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
