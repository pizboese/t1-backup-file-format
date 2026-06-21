# Torso T-1 backup (`.t1`) ⇄ MIDI

Reverse-engineering the Torso T-1 sequencer's backup format to import/export patterns as MIDI.

> **Branch: work on `main` directly** until a stable baseline is established (do not branch per
> change for now). Commit freely to `main`.

## Goal & current status
- **Steps 1-64 + Cycles: DECODED, synthesized, and HARDWARE-VERIFIED** (`make_cycle_hwtest.py`
  → `hwtest/project_cycle_hwtest.zip` loaded & rendered correctly on device). 64-byte gate,
  cycle count, step-group page, per-cycle pitch/param/step-seq overrides; the per-pattern
  end-marker rule and saved cursors are nailed down. Sources archived in `samples/15`, `samples/16`;
  both device banks rebuild byte-for-byte (`test_roundtrip.py`). See FORMAT.md.
- **`.t1 → MIDI` exporter: DONE** and verified end-to-end (incl. on-device round-trip).
  Handles pulses, loop length, per-track timing/division, track pitch + chords, per-step
  pitch locks (incl. chords), velocity + per-step locks, sustain + per-step locks,
  multi-channel routing, root, scale.
- **`MIDI → .t1` importer: WORKING, hardware-verified — INCLUDING CHORDS** (multi-note pitch
  locks render as block chords on device, from a synthesized non-lock template — no per-track
  device-template cloning needed). Covers: bank loading, channel routing, gates, single-note +
  chord pitch locks, velocity, sustain, multi-pattern containers. Proven by `test_roundtrip.py`
  (**all sample banks rebuild byte-for-byte**) **and on real hardware** (`hwtest/project_locksummary.zip`
  loaded & rendered correctly: 2 patterns × {single-note, scale, chords, velocity-ramp, sustain}).
- **Fixes / choices made during hardware verification:**
  1. **Final-block lock terminator** (CONFIRMED format rule, invisible to parser/roundtrip — no
     sample exercised it): the bank's last block, if it carries locks, uses a terminator byte =
     `last_tc-1` (+ a `00` pad on multi-pattern banks), not `00`. Wrong value → device **rejects
     the whole bank and reinitialises it**. Fixed via `build_bank(..., final_has_locks=)`.
  2. **Importer encodes chords as `pc=1` default + per-step pitch locks** — a device-verified,
     *safe choice*, NOT a format requirement. ⚠️ Multi-pitch (chord) **defaults ARE valid on
     stepped tracks** — `hwtest/fromT1/handmade2.zip` has a stepped track whose pulses without a
     per-step lock play the `pc=3` default chord, and it loads fine. The stored-state is
     byte-identical across pc=1/2/3 (no secondary count field). Our earlier `pc=3` load-failure
     with the *synthesized* template is **unexplained** (likely a stored-state interaction) and
     is folded into the open RE below — do not treat "chords need pc=1" as a rule.
- **✅ CHORD BLOCKER RESOLVED (was: per-track stored-state region).** Decoded via 3 random-reroll
  / sweep backups (`samples/12–14`, tool `t1_blockdiff.py`). The steps-region splits into
  **Zone A** = per-param `<value><17-B random seq>` records (random buffer the importer may clone
  freely) and a **trailing per-block lock-summary** at `steps+0x29c`. The blocker was NEVER about
  chord *voicing* — Style lives at `steps+0x13d` (poly 0-4 / mono 8-12) and was already 0. Three
  real, hardware-confirmed rules govern whether a lock track loads (all now handled by the importer):
  1. lock blocks need the summary present (`+0x29c`=1), not the non-lock template's zeros;
  2. a pc=1 (single-default) track must be fully or not-at-all pitch-locked (no partial);
  3. the end-marker `steps+0x2b6` is position-dependent (`1` first track, else `N-i`).
  The final-block end-marker must not collide with the Form-X terminator (`build_bank` handles).
  See FORMAT.md "TRUE chord blocker" / "Final lock block". ~Most of the 695 bytes are now
  accounted for (random buffer + decoded params + lock-summary); remaining unknowns are minor.
- Format byte-map is documented in **`FORMAT.md`** (read it first). Container, lock terminators
  (incl. final-block exception), groove `entry_count` packing, bank summary/cursor, and the
  stored-state-region findings are all there.

## 📖 Device manual — for mapping any remaining features → bytes
**https://docs.torsoelectronics.com/t1/introduction** — the official T-1 manual (JS SPA; deep
pages like `…/t1/parameter-reference/shape/voicing-style` are reachable directly). Mine it for
the per-track parameter list (Pitch, Style/Voicing, Harmony, Repeats, Cycles, Rotate, Random,
Phrase, Accent, Time, Chance, …) to name the still-undecoded steps-region params. NOTE: **Style
(`steps+0x13d`, poly 0-4 / mono 8-12) is decoded and was NOT the chord blocker** — the blocker
was the trailing lock-summary + load rules (resolved; see FORMAT.md).

## Tools (Python 3, no dependencies)
- `t1_format.py` — parser. `parse_bank(path)` → `{patterns: [[track,…],…], tracks:[…]}`.
  CLI: `python3 t1_format.py FILE.t1` prints decoded tracks + per-step locks.
- `t1_to_midi.py` — exporter. `python3 t1_to_midi.py FILE.t1 -o OUTDIR [--bpm 120]`
  writes one `.mid` per non-empty pattern (Type 1; 96 PPQN to match the device).
- `midi_to_t1.py` — importer. `python3 midi_to_t1.py -o OUT.t1 IN1.mid [IN2.mid …]`
  `[--div 16] [--length N] [--template FILE]`. Each `.mid` → one pattern; each MIDI channel
  with notes → one track; chords/pitch-changes → pitch locks; per-step velocity/length →
  groove locks. Scale/root default Chromatic/C (absolute pitch plays exactly). **Imports a
  single 16-step base cycle only — it does NOT yet emit cycles or steps>16 from MIDI** (the
  *synthesis* primitives exist; only the MIDI→cycle mapping is missing — see "Cycles in MIDI
  import" under Next steps).
- `test_roundtrip.py` — self-test: rebuilds every sample bank byte-for-byte (run after any
  change to the block/container synthesis or the parser). Now includes the multi-pattern/
  lock-last regression (`samples/11_multipattern_locklast/handmade.t1`).
- `t1_cycles.py` — decode steps-to-64 + the **cycles** feature: `python3 t1_cycles.py FILE.t1`
  prints per-track cycle count, step-group page, per-cycle track-pitch overrides, and per-cycle
  step-sequence records (gate + per-step pitch/groove locks). See FORMAT.md "STEPS up to 64 + CYCLES".
- `t1_annotate.py` — raw RE helper: `show` / `diff A B` / `sweep F…` (monotonic-byte finder).
- `make_cycle_hwtest.py` — synthesizes a from-scratch steps-64 + cycles bank and splices it into
  a real backup → `cycle_hwtest.t1` + `project_cycle_hwtest.zip` (device-loadable). Proves cycle
  *synthesis* (the two device cycle banks rebuild byte-for-byte in `test_roundtrip.py`).
- `make_hwtest_midi.py` — generates the dependency-free test MIDI (`hwtest/p1_routing.mid`,
  `hwtest/p2_dynamics.mid`) used for hardware verification.

Quick check: `python3 t1_to_midi.py samples/09_perstep_polyphony/bank.t1 -o /tmp/out`
Importer check: `python3 test_roundtrip.py` (expect "ALL PASS")

## Loading on the device (full backup zip — per-bank import is NOT possible)
The T-1 restores a **full backup zip**, not a single `.t1`. Structure (all entries `./`-prefixed,
**Stored**/uncompressed): `0.t1`…`7.t1` (one per bank), `Settings.json`, `Wifi.json`. To test a
synthesized bank **non-destructively**, splice it into a real backup the user exports:
unzip their backup → replace one slot's `.t1` (we used **slot 0**, the empty bank) → repackage
with identical layout (use Python `zipfile`, `ZIP_STORED`, exact `./` names). Banks 1–7 +
settings must stay byte-identical. See `hwtest/` for a working example builder.
**TODO: fold this into `midi_to_t1.py`** (`--zip BACKUP.zip --slot N` → emit a loadable zip).

### How to build the loadable backup zip (recipe)
Given a synthesized `BANK.t1` and the user's real `ORIG.zip`, replace one slot and repackage:
```python
import zipfile, os
SRC = "orig_extracted"          # unzip ORIG.zip here first (keeps banks 1-7 + JSON intact)
TEST_BANK = "BANK.t1"           # your synthesized bank
OUT = "project.zip"; SLOT = 0   # which 0.t1..7.t1 to overwrite (0 = usually the empty bank)
DT = (1980, 1, 1, 0, 0, 0)      # fixed timestamp; the device ignores it
names = ["./", "./0.t1","./1.t1","./2.t1","./3.t1","./4.t1","./5.t1","./6.t1","./7.t1",
         "./Settings.json","./Wifi.json"]
def payload(n):
    if n == "./": return None                                   # directory entry
    if n == f"./{SLOT}.t1": return open(TEST_BANK, "rb").read()  # <- spliced-in bank
    return open(os.path.join(SRC, n[2:]), "rb").read()           # untouched original
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_STORED) as z:
    for n in names:
        data = payload(n); zi = zipfile.ZipInfo(n, date_time=DT)
        zi.compress_type = zipfile.ZIP_STORED
        if data is None: zi.external_attr = (0o40755 << 16) | 0x10; z.writestr(zi, b"")
        else:            zi.external_attr = 0o644 << 16;            z.writestr(zi, data)
```
**Rules that matter:** every entry is `ZIP_STORED` (no compression); names carry the `./` prefix
and there is a leading `./` directory entry; keep the exact 11-entry order; banks 1–7 +
`Settings.json` + `Wifi.json` must stay **byte-identical** to the original (verify with `cmp`).
Then the user restores `project.zip` via the T-1 Backup menu. (Restore overwrites all 8 banks +
settings, so always splice into a real backup — never ship a zip with only your test bank.)

## `hwtest/` — hardware-verification working set
- `cycle_hwtest.t1`, `project_cycle_hwtest.zip` — **from-scratch steps-64 + cycles bank +
  spliced backup; HARDWARE-VERIFIED** (2 patterns, rising complexity: step counts, cycle counts,
  per-cycle pitch/param/gate/per-step edits). Regenerate with `python3 make_cycle_hwtest.py`.
- `p1_routing.mid` / `p2_dynamics.mid` — test patterns (routing+pitch+chords / velocity+sustain).
- `hwtest_locksummary.t1`, `project_locksummary.zip` — **current importer output + spliced backup;
  HARDWARE-VERIFIED** (chords + all load-rules render correctly from a synthesized template).
- `hwtest.t1`, `project.zip` — earlier importer output (before the lock-summary fix); its bank
  loaded but mis-rendered chords + dropped a pattern.
- `hwtest_handtmpl.t1`, `project_diag.zip` — diagnostic bank with stored-state cloned per-track
  from real device blocks; loaded & rendered correctly (the proven clone-from-device fallback).
- `fromT1/` — **device-authored reference files** (ground truth): `handmade.zip` (our target,
  programmed by hand on the T-1 = `samples/11`), `handmade2.zip` (pc=3 chord-default variant),
  `project.zip` (device's re-export of our broken bank), `original_backup.zip` (a full 8-bank
  real backup — the splice base for building loadable test zips).

## Format essentials (full detail in FORMAT.md)
- A `.t1` = one **bank**. Layout: `05 "2.1.4"` header, a `track-count` byte, packed
  **803-byte track blocks**, patterns separated by 12-byte gaps, trailer ending `os|t`.
  Only non-empty tracks/patterns are serialized (sparse). The **autosave** zip is a different
  container (one file per pattern, hash-named) but embeds the **identical** track block.
- Parse blocks by the **landmark** `00 01 02 … 0b` (call its offset `run`); each block has one.
- **Determinism**: re-exporting unchanged content is byte-identical → clean diffs.
- Pitch is **absolute**, C3 = `0x3c` (60); values can exceed 127 (internal). Scale/root only
  quantize on playback, they do not change the stored pitch.
- Timing: division = ticks/step at **96 PPQN**, `value × divisor = 384`.

### ⚠️ Gotchas that bite the parser
1. **Pitch list is variable-length** (`count` at block+0x02, then `count` pitch bytes at
   block+0x06) — it shifts everything after it.
2. **Per-step lock region is variable-length** and inserted *before* the `steps` field, so
   `steps`/division/scale/velocity/sustain/midi-mask/root all **shift**. `t1_format.py` parses
   the lock lists forward to relocate them. Don't use fixed absolute offsets for these.
3. Per-step locks are stored newest-first; pitch locks support chords (`pitch_count:u32`).
4. **Final-block lock terminator** is special (byte = `last_tc-1`, + `00` pad on multi-pattern):
   wrong → device rejects the bank (a real format rule; see status + FORMAT.md). Separately, the
   importer encodes chords as `pc=1` default + per-step locks by *choice* — multi-pitch defaults
   are also valid (see status bullet 2), not a rule.
5. **Stored-state region is not noise** — it carries a field that governs chord rendering; clone
   it from a *real device* block of a matching track type, not a synthesized one.

### Device value scale (velocity / sustain) — use the N/16 grid
The device shows/enters these as 16 LED steps; **stored byte ≈ N×8** (e.g. 8/16 → 64, 16/16 →
127). **Sustain** = note length relative to the track division: ~byte 64 ≈ 50% = **one full
step**; higher overlaps into the next step; min = shortest. Importer currently stores sustain
`round(steps×64)-1` (1 step→63) — **TODO: change default to 64** to match the device, and pick
test velocities/sustains on the N×8 grid so on-device LED readings line up for easy comparison.

## `samples/` — archived backups (the experimental record)
Each folder is one experiment that decoded part of the format; `.t1` files are extracted
(zips removed). See **`samples/README.md`** for the per-folder detail (programmed values,
LED readings, and what each one decoded, with tables).

## Next steps (start here in a new conversation)
**✓ DONE this session — chord import (the old Priority 1 blocker).** The per-track steps-region
is carved into `[random buffer | params | trailing lock-summary]`; chords + all lock load-rules
are decoded and the importer is hardware-verified. Method/tooling that worked: `t1_blockdiff.py`
(random re-roll to isolate the buffer, then sweeps); experiments in `samples/12–14`; full decode
in FORMAT.md. The remaining steps-region work is now optional polish, not a blocker:
   - Name the other ~8 Zone-A random sequences (re-roll each parameter; see FORMAT.md Zone A).
   - Sweep remaining params (Repeats, Rotate, Phrase, Harmony, Chance…) to expose them as
     importer features, using the manual + monotonic sweeps. (Cycles + Steps are done.)

**Cycles in MIDI import (not started — the only missing piece is the MIDI→cycle MAPPING).**
The *byte synthesis* is DONE and hardware-verified: `build_track_block` already accepts
`steps` (1-64), `step_group`, and `cycles`/`cycle_pitch`/`cycle_records`/`cycle_params` (see its
docstring + FORMAT.md "STEPS up to 64 + CYCLES"). `make_cycle_hwtest.py`'s `track()` helper is a
**worked, hardware-verified example** of turning a high-level per-cycle spec into those kwargs —
copy its shape. What's missing is in `map_channel_to_track`/`midi_to_pattern`, which today emit
only a single 16-step base cycle (`cycles=4`, no per-cycle data). To add cycles you must:
1. **Decide how a `.mid` expresses cycles** (the real open question — MIDI has no cycle concept).
   Options: one `.mid`/clip per cycle; a marker-meta convention; or N×length bars where bar *k* =
   cycle *k*. Then diff each cycle against the base and emit only the deltas.
2. Translate those deltas to the kwargs, respecting the decoded rules:
   - cycle indices are **0-based**, stored **descending**; **every edited cycle needs a step-seq
     record** (gate = base gate if unchanged) even if only its pitch/param changed;
   - per-cycle **track pitch** → `cycle_pitch` (header); **sustain/steps/division/scale/vel/root**
     → `cycle_params` (ids in FORMAT.md); **gate + per-step locks** → `cycle_records`;
   - a per-step lock only sounds if **that cycle's gate has a pulse on that step**;
   - pass the right `end_mark` (i+1, last track of pattern = 1) — `midi_to_pattern` already does.
3. Also wire steps>16 and `step_group` through `map_channel_to_track` (currently capped at 16).

**Priority 2 — importer polish**: velocity/sustain on the N×8 grid + sustain default 64 (see
above); fold the **backup-zip builder** into `midi_to_t1.py` (`--zip`/`--slot`); scale/root
mapping (currently Chromatic/C so absolute pitch plays); choose track default pitch to minimise
locks.

**Priority 3 — other unknowns**: track type (Note/CC/FX), mute/enable, "free" (non-fixed)
division mode, scale-interval tables in the exporter.

### Working with the device owner (RE methodology)
- The user owns the hardware and produces backups on request; **prefers one backup per request**
  (pack variations across tracks/patterns). They manual-save → Backup → share the **full zip**.
- **Monotonic sweeps**: vary one parameter = its index across blocks; the field shows up as a
  byte counting `1,2,3,…`, cutting through per-track stored-state noise.
- **Determinism**: re-exporting unchanged content is byte-identical → before/after diffs are
  noise-free. The device has no numeric display (values read as 16 LEDs ≈ 8 units each).
- Ground-truth references live in `hwtest/fromT1/` and `samples/`.
