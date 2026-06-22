---
name: midi-to-t1
description: Guided import of MIDI file(s) into a Torso T-1 backup. Use when the user wants to turn .mid files into a device-loadable .t1/zip — it inspects the MIDI, recommends a mapping (split tracks, cycles, steps), asks the user to confirm, then runs midi_to_t1.py and verifies. Triggers on "import this midi to the T-1", "make a T-1 backup from these mid files", "load X.mid on the T1".
---

# MIDI → Torso T-1 import (guided)

The mapping logic lives in `midi_to_t1.py` (testable, non-interactive). This skill is the
**interview + orchestration** layer: inspect the source, recommend, ask, run, verify. Never
re-implement byte synthesis here — always shell out to `midi_to_t1.py`.

## 1. Inspect the source first (don't guess)
For each `.mid`, report structure before proposing anything:
```bash
python3 - <<'PY'
import midi_to_t1 as M
for f in ["FILE.mid", ...]:
    ppqn, smf = M.read_midi_tracks(f)            # per-SMF-track (split view)
    print(f"{f}: ppqn={ppqn}")
    for name, notes in smf:
        chans = sorted({n[4] for n in notes})
        bars = (max(n[1] for n in notes)) / (ppqn*4)
        print(f"   SMFtrk {name!r}: {len(notes)} notes, ch{chans}, ~{bars:.2f} bars")
PY
```
Key things to surface: how many **musical parts** (SMF tracks), whether parts **share a channel**
(→ need `--split-tracks`), and the **bar count** (→ whether cycles help).

## 2. Decide the mapping WITH the user
Ask (AskUserQuestion) the things the source leaves ambiguous — but if the user already gave a
table or named files by convention, SKIP the interview and use that. Three placement methods:

- **Interview (default):** ask which files go to which patterns/tracks. Each input `.mid` → one
  pattern (slots 0,1,2,…); within it, each SMF track (`--split-tracks`) or MIDI channel → a track.
- **Table from the start:** the user hands you a placement table → write it as a `--plan` JSON and
  run that (see §3). Most explicit; supports multiple files/SMF-tracks into one pattern as separate
  tracks, sparse pattern slots, and per-track options.
- **Filename convention:** files named `pattern1_track2.mid` → use `--by-filename` (pattern# →
  slot#-1, track# orders tracks; each file = one track).

Then settle the per-track shape (recommendations):
- **Parts → tracks:** if a file has >1 SMF part (esp. sharing a channel), use `--split-tracks` (or,
  in a plan, one trackspec per `smf_track`) so each part is its own T-1 track.
- **Length / cycles:** a T-1 track is **16 steps shown, up to 64 stored**; one pattern = 16 tracks.
  - 1 window long → no cycles.
  - **multi-bar** → `--cycles bars`: consecutive `--steps`-long windows become cycles (window k →
    cycle k; proven). Confirm **cycle count** (auto = #windows with notes, max 16) and **steps**
    (1–64, default 16). Too long for 16 cycles → coarsen `--div`, raise `--steps`, or split across
    patterns/banks; flag the trade-off, never silently truncate.

## 3. Choose the backup target, then build
Ask TWO things: (a) **fresh single-bank file** or **based on an existing backup**, and (b) **which
bank (0–7)** to target.

- **Fresh file:** `--new-backup --slot N` → a minimal zip with just `./` + `./N.t1` (no other banks,
  no settings — the device's project-export shape). Hardware-confirmed to restore on the T-1.
- **Based on existing:** `--zip THEIR_BACKUP.zip --slot N` (banks ≠N + settings stay byte-identical;
  non-destructive, hardware-proven — restoring overwrites all 8 banks but the others are preserved
  as-is). Ask the user to export a backup (Backup menu) and share it; or use
  `hwtest/fromT1/original_backup.zip` as a splice base for a quick test.

```bash
# simple / interview or filename:
python3 midi_to_t1.py -o OUT.t1 IN1.mid [IN2.mid …] \
  [--split-tracks] [--by-filename] [--cycles bars] [--steps 16] [--cycle-count N] [--div 16] \
  (--new-backup | --zip REAL_BACKUP.zip) --slot N        # writes OUT.t1 + OUT.zip

# table-driven (skill writes plan.json from the interview):
python3 midi_to_t1.py -o OUT.t1 --plan plan.json
```
`--plan` JSON schema (see `run_plan` docstring): `{"backup":"new"|"<path>", "bank":N, "patterns":[
{"slot":0,"tracks":[{"midi":"a.mid","track":1,"smf_track":0,"cycles":"bars","steps":16}, …]}]}`.

## 4. Verify before handing it over
```bash
python3 t1_format.py OUT.t1            # tracks, steps, cycles, locks look right?
python3 t1_cycles.py OUT.t1           # per-cycle records correct (if cycles used)?
python3 test_roundtrip.py OUT.t1      # structural sanity (rebuilds cleanly)
```
Confirm: track count/channels, cycle count, chords on the right steps, sensible sustain. Then tell
the user the exact slot/patterns/tracks and that they restore `OUT.zip` via the T-1 Backup menu.

## Facts to honor (see CLAUDE.md / FORMAT.md — source of truth)
- **Pitch absolute**, C3=60; scale/root default Chromatic/C (absolute pitch plays exactly).
- **Velocity** 0–127 stored 1:1. **Sustain** is a log law: byte **64 = one full division**; length
  doubles every 16 byte units (12/16 LED=4 steps, 14/16=8, full=16).
- **Cycles** use the natural encoding (base = cycle 0 with its locks; a per-cycle record only when a
  cycle differs). `build_cycle_track` already does this — don't hand-roll it.
- Per-step locks lock **every active step** (avoids the partial-lock drop rule).
