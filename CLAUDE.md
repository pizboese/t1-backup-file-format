# Torso T-1 backup (`.t1`) ⇄ MIDI

Reverse-engineering the Torso T-1 sequencer's backup format to import/export patterns as MIDI.

## Goal & current status
- **`.t1 → MIDI` exporter: DONE** and verified end-to-end (incl. on-device round-trip).
  Handles pulses, loop length, per-track timing/division, track pitch + chords, per-step
  pitch locks (incl. chords), velocity + per-step locks, sustain + per-step locks,
  multi-channel routing, root, scale.
- **`MIDI → .t1` importer: NOT BUILT YET** — the main next task. Synthesis is proven feasible
  (a hand-patched bank loaded on the device; **there is no checksum**).
- Format byte-map is fully documented in **`FORMAT.md`** (read it first).

## Tools (Python 3, no dependencies)
- `t1_format.py` — parser. `parse_bank(path)` → `{patterns: [[track,…],…], tracks:[…]}`.
  CLI: `python3 t1_format.py FILE.t1` prints decoded tracks + per-step locks.
- `t1_to_midi.py` — exporter. `python3 t1_to_midi.py FILE.t1 -o OUTDIR [--bpm 120]`
  writes one `.mid` per non-empty pattern (Type 1; 96 PPQN to match the device).
- `t1_annotate.py` — raw RE helper: `show` / `diff A B` / `sweep F…` (monotonic-byte finder).

Quick check: `python3 t1_to_midi.py samples/09_perstep_polyphony/bank.t1 -o /tmp/out`

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

## How we get more data (workflow with the device owner)
The user owns the hardware and produces backups on request. Methodology that worked:
- **Monotonic sweeps**: vary one parameter = its index across the 16×16×16 grid
  (banks/patterns/tracks); the real field shows up as a byte counting `1,2,3,…`, cutting
  through each block's per-track random-sequence noise. Used for channel/steps/scale/root.
- **Same-bank before/after**: change one thing, re-export; the diff is noise-free (determinism).
- The user **prefers one backup per request** now — pack variations across tracks/patterns.
- Ask the user to **manual-save then Backup** (per-bank `.t1`), and to record values the
  device shows (it has no numeric display — values read as 16 LEDs ≈ 8 units each, 0–127).

## `samples/` — archived backups (the experimental record)
Each folder is one experiment that decoded part of the format; `.t1` files are extracted
(zips removed). See **`samples/README.md`** for the per-folder detail (programmed values,
LED readings, and what each one decoded, with tables).

## Next steps
1. **Build `midi_to_t1.py`** (MIDI → `.t1`): map channels/tracks → T-1 tracks; notes → gate +
   pitches (chords & per-step pitch locks); velocity/length → groove. Generalize the proven
   template-patching to variable sizes (chords/locks change block length); rebuild pattern
   wrappers + bank trailer/summary. Start from `samples/10_synth_test_import` as a template.
2. **Scale quantization** in the exporter (optional): confirm the scale interval tables
   (Major/Minor/Penta/Hira/Iwato/Tetra) + apply root, to emit out-of-scale notes as played.
3. Decode remaining: track type (Note/CC/FX), mute/enable, "free" (non-fixed) division mode.
4. Verify the full exporter on a richer hand-made pattern.
