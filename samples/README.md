# Sample backups — experimental record

Each folder is one experiment used to reverse-engineer the `.t1` format. Backups are extracted
(zips removed). Files are per-bank `0.t1`-style backups unless noted. Offsets below are
block-relative via the `run` landmark (`00 01 … 0b`); see `../FORMAT.md` for the full byte-map.

---

## 01_pulse_sweep/ — the gate/step array
8 banks, each with N pulses on steps 1..N of Pattern 1 / Track 1.

| File | Pulses on steps |
|------|-----------------|
| `0pulses.t1` | none (empty bank, 23 B) |
| `1pulses.t1` | 1 |
| `2pulses.t1` | 1,2 |
| … | … |
| `7pulses.t1` | 1–7 |

**Found:** gate array at `run+0x0c`, 16 bytes, `01`=pulse / `00`=empty. Empty bank is only
23 bytes (header+footer); a full track block appears once a track has content.

## 02_determinism/ — determinism control
Re-export of `01_pulse_sweep` **without any changes**. All 8 files are **byte-identical** to
their originals → the format is deterministic, so before/after diffs on the same bank are
noise-free. (The high-entropy per-track region is stable stored state, not random-per-save.)

## 03_strides/ — block & container layout
- `manual_5tracks.t1` — one bank, 3 patterns (P1: 3 tracks, P2: 1, P3: 1), single pulse per
  track on steps 1,2,3,4,5 respectively.
- `autosave_example/` — the same content as an **autosave** snapshot (one hash-named file per
  pattern + a 14 B global + a 22 B index).

**Found:** track block = **803 bytes**, packed; `track-count` byte at file `0x06`; patterns
separated by a **12-byte** gap (block deltas `803,803,815,815`). The 803-byte block is
**byte-identical** between manual and autosave containers.

## 04_pitch_vel_sustain/ — track pitch (+polyphony), velocity, sustain
One bank, P1/T1, pulse on step 1. Cumulative single changes:

| File | Change | Stored bytes |
|------|--------|--------------|
| `a.t1` | default (track pitch C3) | pitch `3c`=60 |
| `b.t1` | track pitch → highest | pitch `83`=131 |
| `c.t1` | track pitch → highest−1 | pitch `82`=130 |
| `d.t1` | pitches highest + highest−1 | `82 83` (2 notes) |
| `e.t1` | pitches highest + highest−1 + C3 | `82 83 3c` (3 notes) |
| `f.t1` | track **sustain** → max | `3f`(63)→`7f`(127) |
| `g.t1` | track **velocity** → max | `64`(100)→`7f`(127) |

**Found:** pitch = `count` (block+0x02) + variable list (block+0x06), absolute, C3=60,
polyphonic; velocity & sustain are 1-byte 0–127 track fields. The pitch list is
variable-length and shifts later fields.

## 05_channel_steps_scale/ — MIDI output, length, scale
One bank, 3 patterns (`bank.t1`, 32 track blocks).

**Pattern 1 — MIDI output sweep (bitmask):**

| Track | Output | Track | Output |
|-------|--------|-------|--------|
| 1–8 | ch 1–8 (default = own ch) | 12 | ch 1+2 |
| 9 | none | 13 | ch 1+2+3 |
| 10 | ch 1 | 14 | ch 1+3 |
| 11 | ch 2 | 15,16 | all 16 |

→ **MIDI out = u16 LE bitmask at `run+0x144`** (bit n = channel n+1).

**Pattern 2 — steps sweep:** tracks 1–8 → STEPS = 1..8 → **steps at `run+0x60`** (default 16).

**Pattern 3 — scale sweep:** Chromatic, Major, Minor, Penta, Hira, Iwato, Tetra, Chromatic
→ **scale at `run+0xa0`** (0=Chromatic … 6=Tetra). Pitch byte stays 60 for all → pitch is
absolute; scale only quantizes on playback.

## 06_root_division/ — root note & timing
One bank, 2 patterns (`bank.t1`).

**Pattern 1 — root sweep:** tracks 1–12 → root C, C#, …, B → **root at `run+0x19f`** (0=C…11=B).

**Pattern 2 — division sweep:** stored as **u16 LE at `run+0x8a`** = ticks/step @96 PPQN,
`value × divisor = 384`:

| Division | /1 | /2 | /4 | /8 | /16 | /32 | /64 | /3 | /6 | /12 | /24 | /48 |
|----------|----|----|----|----|-----|-----|-----|----|----|-----|-----|-----|
| stored | 384 | 192 | 96 | 48 | 24 | 12 | 6 | 128 | 64 | 32 | 16 | 8 |

## 07_perstep_cumulative/ — per-step overrides exist & are variable-length
One bank, P1/T1, pulses on steps 1–4. Cumulative per-step edits:

| File | Change | File grows |
|------|--------|------------|
| `a.t1` | base (no locks) | — |
| `b.t1` | step 1 pitch → +12 (=72) | +7 B |
| `c.t1` | step 1 velocity → max | +7 B |
| `d.t1` | step 1 sustain | +5 B |
| `e.t1` | step 2 pitch → 62 | +6 B |

**Found:** per-step overrides are a **variable-length lock list** inserted before `steps`
(file grows per lock), which shifts later fields. Pitch-lock format:
`[num][step][pitch_count:u32 LE][pitches…]`, newest-first.

## 08_perstep_groove/ — groove-lock format
One bank, P1/T1, pulses 1–9, with per-step groove locks (device has no numeric display;
values read off the 16 LEDs):

| Step | Lock | Decoded | LED reading |
|------|------|---------|-------------|
| 5 | velocity | 40 | 5/16 |
| 6 | velocity | 88 | 11/16 |
| 8 | sustain | 16 | 2/16 |
| 9 | sustain | 120 | 15/16 |

**Found:** groove lock = `[num]` then per lock `[entry_count][step][param][value][00 00 00]`
(7 B), param `0x0a`=velocity, `0x0e`=sustain. Region layout at `run+0x4c`:
`[groove list][pitch list][18 B pad][steps]`.

## 09_perstep_polyphony/ — per-step chords
One bank, P1/T1, pulses 1–4, track default pitch C3, with per-step **chord** locks:

| Step | Per-step pitch lock |
|------|---------------------|
| 2 | C3+E3+G3 → `[60,64,67]` |
| 3 | D3+A3 → `[62,69]` |

**Found:** the pitch lock's `pitch_count:u32` holds multiple pitches → per-step polyphony,
independent of the track's own pitch list.

## 10_synth_test_import/ — synthesized bank (import proof)
`0.t1` was **built by patching a template** (not exported from the device) and **loaded
successfully** on the T-1 → no checksum; synthesis works. Programmed values:

| Pattern | Track | MIDI ch | Pitch | Velocity | Sustain | Length | Scale | Pulses |
|---------|-------|---------|-------|----------|---------|--------|-------|--------|
| 1 | 1 | 1 | C3 | 100 | 63 | 16 | Chromatic | 1,5,9,13 |
| 1 | 2 | 4 | E3 | 127 | 30 | 16 | Major | 1,2,3,4 |
| 1 | 3 | 7 | G3 | 50 | 100 | 8 | Minor | 1,3,5,7 |
| 2 | 1 | 10 | C4 | 90 | 63 | 16 | Penta | 1,8,16 |
| 3 | 1 | 16 | A2 | 110 | 10 | 4 | Iwato | 1,2,3,4 |

All verified on device. (Note: A2 in Iwato/root-C showed snapped to a scale tone → playback
quantizes pitch to scale+root.)

## 11_multipattern_locklast/ — device-authored, multi-pattern + lock-bearing last block
`handmade.t1` was **programmed on the device by hand** to mirror our importer test (2 patterns:
P1 routing/pitch-locks/chords on ch 1-3; P2 velocity ramp + sustain on ch 1-2), then backed up.
It is the **ground-truth reference** that exposed the **final-block lock-terminator** rule
(byte = `last_tc-1`, plus a `00` pad on multi-pattern banks — see FORMAT.md). Our first
synthesized import of this shape was rejected by the device (reinitialised to an empty pattern)
because it wrote the plain `00` terminator. `test_roundtrip.py` now rebuilds this file
byte-for-byte, locking in the fix.

## 12_random_reroll/ — isolate the per-track random buffer
One track copied across 4 patterns, re-rolling ONE parameter's random sequence per copy. Carved
the steps-region into Zone A (`<value><17-B random seq>` records) vs structured bytes. Tool:
`../t1_blockdiff.py`. See `12_random_reroll/README.md`.

## 13_style_sweep/ — decode Style (voicing)
One chord track across 10 patterns, Style = VB1..VB5 (poly) then VB9..VB13 (mono). The single
byte that changed = **Style @ `steps+0x13d`** (poly 0-4 / mono 8-12). Turned out NOT to be the
chord blocker. See `13_style_sweep/README.md`.

## 14_lock_summary/ — the real chord blocker
Two patterns of chord-lock tracks that exposed the trailing per-block **lock-summary** at
`steps+0x29c` and the load rules deciding whether a lock track loads. This decode made
from-scratch chord import work on hardware. See `14_lock_summary/README.md`.

## device_settings/
`Settings.json` and `Wifi.json` as found in a backup — global device configuration
(MIDI routing, clock, CV, etc.), not part of the per-bank pattern data.
