# 17 — base track per-step locks + cycle records (device-authored)

Programmed by hand on the T-1 to verify the one combo no prior sample exercised: a **base track
that carries per-step locks AND also has edited cycles** (the device's own natural/compact cycle
encoding — base = cycle 0 with its locks, records only for cycles that differ). Source backup:
`hwtest/fromT1/base_locks_cycles.zip` (single-bank export: `0.t1` + `Wifi.json`).

One pattern, 3 tracks (16 steps, /16):

| Block | Cycles | Base track (cycle 1) | Records | Verifies |
|------|:--:|------|------|------|
| 0 (ch1) | 2 | pitch-locks all 4 pulses: step1 = chord C3‑E3‑G3, 5=C4, 9=E4, 13=G4 | cyc2 changes step9 → A5 | **base pitch-locks** coexist with a cycle record |
| 1 (ch2) | 2 | groove-locks: step1 sustain **127** (max/16 steps), step5 sustain **0** (min), step9 velocity **16** (2/16 LED) | cyc2 changes the gate (drop 13, add 3) | **base groove-locks** + gate-only cycle; confirms velocity = N×8, sustain min=0/max=127 |
| 2 (ch3) | 3 | chord-locks step1 (C3‑E3‑G3) + step9 (D3‑F3‑A3) | cyc2 new chord on step1; cyc3 **track-pitch → D3** | base chords + multiple records + a track-pitch-only cycle still emits a step-seq record |

**Result:** `test_roundtrip.py` rebuilds `0.t1` **byte-for-byte** → our decoder reads and our
synthesizer (`build_track_block`) emits this layout exactly. The combo is fully verified, so
`midi_to_t1.build_cycle_track` uses the natural encoding (base = cycle 0 with locks; a per-cycle
record only when a cycle differs). Closes the FORMAT.md "base-locks + cycle-records" open item.
