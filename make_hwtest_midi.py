#!/usr/bin/env python3
"""Generate dependency-free Standard MIDI Files for the on-device importer test.

Two patterns, 96 PPQN, 16-step bar (div 16 -> 24 ticks/step):

  p1_routing.mid  — channel routing + per-step pitch locks + chords
    ch1: four-on-the-floor kick (steps 1,5,9,13), C3
    ch2: ascending C-major run (steps 1-8): C D E F G A B C
    ch3: chords: Cmaj(1) Fmaj(5) Gmaj(9) Cmaj(13)

  p2_dynamics.mid — per-step velocity + note-length (sustain) locks
    ch1: crescendo on steps 1-8, C3, velocity 20..127
    ch2: E3 on steps 1,5,9,13; steps 5 & 13 held long (sustain lock)
"""
import struct

PPQN = 96
STEP = PPQN * 4 // 16            # 24 ticks/step at div 16


def vlq(n):
    out = bytearray([n & 0x7f])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7f) | 0x80)
        n >>= 7
    return bytes(out)


def note(chan, step, pitch, vel, length_steps=1):
    """One (start_tick, on_bytes), (end_tick, off_bytes) pair (chan is 1-16)."""
    s = step * STEP
    e = s + length_steps * STEP
    c = chan - 1
    return [(s, bytes([0x90 | c, pitch, vel])),
            (e, bytes([0x80 | c, pitch, 0]))]


def write_smf(path, events):
    """events: list of (tick, raw_event_bytes). Emitted as a format-0 single track."""
    evs = sorted(events, key=lambda x: x[0])
    trk = bytearray()
    last = 0
    for tick, raw in evs:
        trk += vlq(tick - last)
        trk += raw
        last = tick
    trk += vlq(0) + b"\xff\x2f\x00"          # end-of-track
    hdr = b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQN)
    mtrk = b"MTrk" + struct.pack(">I", len(trk)) + bytes(trk)
    open(path, "wb").write(hdr + mtrk)
    print(f"wrote {path} ({len(hdr)+len(mtrk)} B, {len(evs)} note-events)")


# ── pattern 1: routing + pitch locks + chords ───────────────────────────────────────
C3 = 60
MAJOR = [60, 62, 64, 65, 67, 69, 71, 72]     # C D E F G A B C
p1 = []
for st in (0, 4, 8, 12):                      # ch1 four-on-the-floor
    p1 += note(1, st, C3, 100)
for i, st in enumerate(range(0, 8)):          # ch2 ascending run
    p1 += note(2, st, MAJOR[i], 100)
for st, chord in ((0, (60, 64, 67)),          # ch3 chords
                  (4, (65, 69, 72)),
                  (8, (67, 71, 74)),
                  (12, (60, 64, 67))):
    for p in chord:
        p1 += note(3, st, p, 100)
write_smf("hwtest/p1_routing.mid", p1)

# ── pattern 2: velocity + length locks ──────────────────────────────────────────────
p2 = []
VELS = [20, 35, 55, 75, 95, 110, 120, 127]    # crescendo across 8 steps
for i, st in enumerate(range(0, 8)):          # ch1 velocity ramp, C3
    p2 += note(1, st, C3, VELS[i])
for st in (0, 4, 8, 12):                       # ch2 length test, E3 (spaced, no overlap)
    long = st in (4, 12)                        # steps 5 & 13 held 2 steps -> sustain 127 (max)
    p2 += note(2, st, 64, 100, length_steps=2 if long else 1)
write_smf("hwtest/p2_dynamics.mid", p2)
