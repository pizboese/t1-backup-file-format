# `decode/` — complete-format-decode sandbox (process + status)

Quarantined working area for the campaign to account for **every byte** of the `.t1` track block.
Lives only on branch **`completeDecode`** — a **permanent fork**: code never merges to `main`; only
*confirmed* findings are cherry-picked back as **docs** (canonical `FORMAT.md` / root `CLAUDE.md`).

## Why a separate subtree
The shipped toolchain on `main` (`t1_format.py`, `midi_to_t1.py`, `t1_to_midi.py`,
`test_roundtrip.py`, `samples/`) is hardware-verified and must stay green. The campaign acquires raw
backups whose new fields aren't modeled yet — dropped into the shared `samples/` glob they'd turn
`test_roundtrip.py`'s "ALL PASS" red. So everything campaign-related is isolated here.

## Contents
- `samples/NN_*/` — campaign backups (extracted `.t1`). **Kept OUT of the root `samples/` glob on purpose.**
- `FORMAT_DECODE.md` — the live **scoreboard + per-field decode log** (offset, kind, evidence,
  confidence). **The source of truth for what's decoded.**
- `t1_decode.py` — additive field reporting layered on `t1_format` (`import t1_format as F`); keeps
  any edits to the shipped parser minimal/additive.
- `custom_scale.py` — models the custom scale-degree table (see structural findings).
- `test_decode.py` — roundtrips `decode/samples/**` only (reuses `test_roundtrip.test_file`, with
  `decode_rebuild` as the fallback for custom-scale/chord/X banks). **Now ALL PASS** (banks 22 & 23
  rebuild byte-for-byte as of 2026-06-26).
- `decode_rebuild.py` — decode-scope byte-exact rebuild. Models the block HEADER the shipped reader
  hard-codes (`<X:u16><pitch_count:u32>` marker — X is a per-track field, not a constant `0x0c`; the
  variable-length custom **scale-degree table** `<count:u32><degrees>`; block len = 791+scale_count)
  and clones the already-proven tail. Self-contained; touches nothing shipped. See FORMAT_DECODE.md
  "Block header fully modeled".
- `_*.py` — single-use analysis helpers from each bank's decode (block scanners, pair diffs). Kept as
  a reproducible record of method.

## Method (how each field was located)
16 tracks/pattern are stored as ~803-byte blocks. Each campaign pattern was hand-programmed so all
its track blocks are **identical except one target parameter**, stepped one notch per track (a
monotonic ladder); each block also carries a per-track random buffer = noise. Aligning blocks to the
`00 01 02 … 0b` landmark (`run`) keeps offsets in register despite variable-length lock/pitch lists;
the target byte is the one that **counts monotonically** across the aligned blocks. Offsets are
recorded **relative to the `steps` field** (e.g. `+0x79`).

Ladder variants encountered:
- **valueCoarseFine** — equal notches but the stored byte may step by >1 → use a strictly-monotonic scan.
- **bipolar s8** — programmed full-negative → full-positive (centre ≈ 0, range ≈ ±20).
- **note-value u16** — division/time/rate; `value × divisor = 384` (96 PPQN), + a free-mode flag.
- **min/max pair diffs** — set a param to min then max on consecutive tracks → the byte that flips
  is that param's field. (Used to map the whole per-param random region in one pattern.)

Tools (run from repo root): `t1_blockdiff.py --sweep F:i …` (landmark-aligned monotonic finder),
`t1_blockdiff.py F:i F:j` (constant-vs-vary), `t1_annotate.py show/diff/sweep`, `t1_format.py`
(decoded dump incl. per-step locks), `decode/_scan_mono.py` (strictly-monotonic scan, any step size).

## Key structural findings (why some banks desync the parser)
- **The `00 01..0b` "landmark" is actually a scale-degree table** in its default chromatic state
  (`count:u32 LE` + ascending semitone bytes `0..11`). A **custom/user scale** rewrites it to only the
  enabled degrees (C+E+G → `[0,4,7]`), destroying the identity run — so `find_runs` silently skips
  custom-scale tracks. Modeled in `custom_scale.py`. This is why banks 22 & 23 don't roundtrip.
- **Each sequenced parameter is a self-describing record:**
  `value | 16-B modulation sequence (value+0x01..+0x10) | tail | random-amount (value+0x12, s8 ±20)
  | slew (value+0x13) | lock (value+0x14)`. Random **phase** = a left-rotation of the 16-B sequence
  (no stored byte). This resolved all 8 formerly-"unidentified Zone-A runs."

## Samples map (programmed values / LED readings: root `backupNotes.txt` + `BACKUP_CAMPAIGN_INSTRUCTIONS.md`)
| Folder | Theme |
|---|---|
| `21_shape_repeater` (+ `rotate_fixedsteps.t1`) | Pulses, Rotate, Repeats, Ramp, Time, Pace, Range, Phrase, Voicing |
| `22_groove_tonal` | Accent, Groove, Harmony, full Scale table + **custom scales** |
| `23_modes_routing_global` | Note/CC/FX mode, CC encoders, internal routing, mute, FX |
| `24_random` | Random intensity / amount / slew / lock / phase / rate |
| `25_repeat_choke_tail` · `26_phrase_length` · `27_voicing_direction` · `28_groove_length` | extras |
| `29_open_items` | CC#, bipolar positive-half scale, choke/tail, retrigger, selection cursor (B29) |

## Status
Nearly the whole steps-region is **located + documented** in `FORMAT_DECODE.md`. The **decode-scope
roundtrip is DONE** (2026-06-26): banks 22 & 23 now rebuild byte-for-byte (`decode_rebuild.py` models
the block header — `X`, u32 pitch_count/chords, custom scale-degree table — and clones the proven
tail). NOT yet: folded into the shipped parser/importer/exporter. Those are downstream phases (see TODO).

## Ground rules
- **Never break `main`'s working set.** Edits to `t1_format.py` are additive (new reported fields
  only); `test_roundtrip.py` stays ALL PASS as the regression guard.
- **Branch is a permanent fork.** Only confirmed findings move to canonical `FORMAT.md` / root
  `CLAUDE.md`; tooling/code stays here.
- Confirm a field by: adding its sample under `decode/samples/`, getting `test_decode.py` to rebuild
  it byte-for-byte, and having `t1_decode.py` report the programmed ladder.

## Run
```
python3 decode/test_decode.py        # roundtrip the campaign samples
python3 decode/t1_decode.py FILE.t1  # parse + report decoded/located fields
```

## TODO
- [x] **Decode-scope roundtrip.** ✅ DONE 2026-06-26 — `decode_rebuild.py` models the block header
  (X / u32 pitch_count / custom scale-degree table) so `decode/test_decode.py` rebuilds banks **22 &
  23 byte-for-byte** (ALL PASS). Self-contained in `decode/`; the shipped `test_roundtrip.py` + root
  `samples/` glob were untouched and still ALL PASS. (Two minor tail nuances — s32 groove-lock value,
  per-pattern-final terminator — are logged in FORMAT_DECODE.md and cloned rather than re-synthesized.)
- [x] **Decode the four open items** ✅ DONE 2026-06-26 (B29 = `samples/29_open_items`, `project.zip`
  bank 0; rebuilds byte-for-byte via `decode_rebuild`, `decode/test_decode.py` ALL PASS). All four
  closed + a bonus selection-cursor finding (see FORMAT_DECODE.md "Bank 29"):
  - custom encoder **CC#** = `steps+0x16a`+0x17·N (literal CC byte, one before the enable flag; def 70+N);
  - **bipolar scale** = linear s8, **1 unit/notch, centre 0, symmetric −20…+20** (Ramp/Pace/Range/Voicing/Accent all confirmed);
  - **repeat end-behaviour** `steps+0x14a` = enum **0=Tail / 1=Choke** (mutually exclusive, not a bitfield);
  - **retrigger** = per-step gate-byte **bit `0x04`** (`run+0x0c`+step), not a track value;
  - **(bonus) track selection cursor** = selected 0-based track indices in the per-pattern trailer at `last_block_end+2`.
- [x] **Write `decode/BACKUP_INSTRUCTIONS.md`** ✅ DONE 2026-06-26 — the worksheet that drove B29 above.
- [ ] (later) Fold confirmed fields into the shipped `t1_format.py` / `midi_to_t1.py` / `t1_to_midi.py`
  + canonical `FORMAT.md`, each with byte-exact roundtrip proof.
