# Torso T-1 `.t1` backup format — reverse-engineering notes

Status: **export + import working**. Firmware `2.1.4`. One `.t1` file = one **bank**.
Format is a flat, **deterministic** byte serialization (re-exporting unchanged content
yields byte-identical files). The full container (track blocks + pattern wrappers + bank
trailer) is reproduced **byte-for-byte across all 32 sample banks** by `test_roundtrip.py`,
which is what makes synthesis (MIDI → `.t1`) reliable.

Legend: offsets are 0-based hex. `u8` = one byte. "confirmed" = proven by a controlled
backup sweep; "hypothesis" = inferred, not yet isolated.

## Two container formats (same inner track block)
The device produces two zip layouts:
- **Per-bank backup** ("Backup" menu): one `<bankindex>.t1` file per used bank
  (the original `0.t1`..`7.t1`). Header 11 B, then track blocks, then a 24 B trailer.
- **Autosave snapshot**: a folder `autosave/` with hash-named files — **one file per used
  pattern** (track blocks concatenated inside), plus a 14 B global file and, with 2+
  patterns, a 22 B index file. Per-pattern file: header 9 B, track blocks, 12 B trailer.

Both embed the identical **803-byte track block**. Offsets below are given block-relative
where possible so they apply to both containers.

## Track block — 803 bytes (CONFIRMED), block-relative offsets
Tracks are stored as a packed array of 803-byte blocks (only non-empty tracks serialized).
A `track-count` byte precedes them (file offset `0x06`), incrementing 1 per track.

**The block has a variable-length region (the pitch list), so offsets after it shift by
`pitch_count`.** Best to parse by landmarks, not absolute offsets.

| Block off (1 pitch) | Size | Meaning | Status |
|---------------------|------|---------|--------|
| `0x00`–`0x01` | 2 | `0c 00` block marker | confirmed |
| `0x02`        | 1 | **pitch count** (number of selected pitches; chords add 1 each) | confirmed |
| `0x03`–`0x05` | 3 | `00 00 00` | confirmed |
| `0x06`        | N | **pitch list**, 1 byte/pitch, linear semitones, **C3 = `0x3c` (60)**; range exceeds 127 (internal, not raw MIDI) | confirmed |
| `+0x00`…      | 5 | `00 0c 00 00 00` (after pitch list) | confirmed |
| `+0x05`…      | 12 | the run `00 01 … 0b` (landmark before step array) | confirmed |
| `+0x11`…      | 16 | **STEP / GATE array** (1 B/step, `01`=pulse) | confirmed |
| later         | 1 | **track velocity**, default `0x64` (100), max `0x7f` (127) | confirmed |
| later         | 1 | **track sustain/length**, default `0x3f` (63), max `0x7f` (127) | confirmed |
| later         | … | per-step records `00 00 00 <id> 00 <vel=64> <17 B>` — per-step groove/pitch/random | open |

### Parsing by the `run` landmark (CONFIRMED, iteration 5)
Let `run` = file offset of the `00 01 02 … 0b` sequence (one per block). Pre-pitch fields are
relative to block start; everything after the pitch list is at a **fixed offset from `run`**
(pitch-count-independent):

| Field | Location | Notes |
|-------|----------|-------|
| pitch count | block+`0x02` | block start = `run − 0x0b − pitch_count` |
| pitch list  | block+`0x06`, 1 B each | **absolute, C3=`0x3c`(60)**, scale-independent; >127 = internal |
| **gate array** | `run+0x0c`, 16 B | `01`=pulse |
| **steps (length)** | `run+0x60` | default 16; loop length |
| **division** | `run+0x8a`, u16 LE | ticks/step @96 PPQN; `value × divisor = 384` (/16 default = 24). Fixed divisions only; "free" mode TBD |
| **scale** | `run+0xa0` | 0=Chromatic,1=Major,2=Minor,3=Penta,4=Hira,5=Iwato,6=Tetra |
| **velocity** | `run+0xdb` | 0–127, default `0x64`(100); device shows over 16 LEDs |
| **sustain** | `run+0x105` | 0–127, default `0x3f`(63) |
| **MIDI out mask** | `run+0x144`, u16 LE | bit n = channel n+1; default = track's own channel bit |
| **root** | `run+0x19f` | 0=C … 11=B |

Pitch → MIDI note = stored byte directly (C3=60). Clamp/transpose values >127 for export.
Scale is a display/quantize index only; it does not change the stored pitch.

### Validated by import round-trip (synthesized bank loaded on device)
- A hand-patched `.t1` loads fine → **no checksum / integrity field** in the format.
- **velocity & sustain are 0–127** (device shows them across 16 LEDs, ~8 per LED). Stored
  byte = the real value.
- Manual gate patterns load as-authored (rhythm is NOT regenerated from Euclidean on load).
- **Pitch is scale-quantized on playback/display**: stored value is absolute, but if the
  track's Scale (+root) doesn't contain it, the device snaps to the nearest scale tone
  (e.g. A2 in Iwato/root-C → F#/G#). Faithful export of non-chromatic tracks needs the
  **root** field + a quantizer.

### Per-step overrides ("locks") — variable-length list (iteration 7)
Overrides are NOT fixed slots: they are a variable list inserted in the zero-gap just before
the per-step random region (file grows ~5–7 B per lock). Locks are stored newest-first.

**Pitch locks (CONFIRMED):**
```
[num_pitch_locks:u8]  then per lock:  [step:u8 0-based] [pitch_count:u32 LE] [pitch:u8 ...]
```
e.g. step-1 → 72: `01 | 00 01000000 48`; +step-2 → 62: `02 | 01 01000000 3e | 00 01000000 48`.
Pitch values absolute (C3=60); polyphonic per step supported.

**Groove locks (CONFIRMED, iteration 8 + import RE):**
```
[num_groove_locks:u8]  then per lock:  [entry_count:u8][step:u8 0-based]
                                       then entry_count × [param:u8][value:u8][00 00 00]
```
param `0x0a`=velocity, `0x0e`=sustain; value 0–127. One lock record per step; **all groove
params for that step share the record** (entry_count = how many). A single-param record is
7 B; a step with both velocity+sustain is 12 B (entry_count=2, two 5-B param entries,
newest param first). Verified: step5 vel=40, step6 vel=88, step8 sus=16, step9 sus=120
(matched device LEDs), and `07_perstep_cumulative/d,e` (step-1 sustain+velocity combined).

**Lock terminator (CONFIRMED, import RE):** a track block that carries **any** lock (groove
or pitch) has **one extra `00` byte appended after the steps region** (block grows by 1,
once, regardless of lock count). Lock-free blocks have no terminator.

**Final-block exception (CONFIRMED on device):** the **bank's very last block**, when it
carries locks, uses a *different* terminator: the byte is **`last_tc - 1`** (the last
pattern's track-count − 1, i.e. the same value as that pattern's end-trailer), **not** `00`;
and **multi-pattern banks append one extra `00`** after it (so the terminator is 2 bytes
`<last_tc-1> 00`). Single-pattern banks (`08`/`09`: `last_tc-1 = 0`) reduce to the plain
single `00`, which is why this went unnoticed until a synthesized **multi-pattern bank with a
lock-bearing last block** was loaded — the device **rejected the whole bank and reinitialised
it** (shown as an empty pattern with one default pulse). A hand-built reference of the same
shape (`samples/11_multipattern_locklast/`) revealed it; `midi_to_t1.build_bank` now patches
this via `final_has_locks`, and `test_roundtrip` rebuilds that reference byte-for-byte.

**Per-track "stored-state" / steps-region — DECODED (chord blocker RESOLVED, hardware-verified).**
The **695-byte (`0x2b7`) steps-region** (`steps`..block end) is **not inert random data**. It is
now understood as `[Zone A: param table | params | trailing lock-summary]`, and a from-scratch
synthesized bank with chords loads & renders on device. The detailed decode + the three
hardware-confirmed lock load-rules are in the sections below ("Steps-region carved into TWO
zones", "TRUE chord blocker", "Final lock block"). Historical note: an earlier bank built by
cloning a *synthesized* (non-lock) template and patching only 9 field offsets **loaded but
mis-rendered chords + dropped a later pattern** — that was the trailing lock-summary being absent,
not a voicing field. Single-note pitch locks and groove locks render fine regardless of the
random bytes; the remaining undecoded bytes are non-critical params (Repeats/Cycles/Rotate/…).

**Region layout (CONFIRMED):** after the 16-byte gate, at `run+0x4c`:
`[groove list][pitch list][18 B pad][steps]`. The lists are variable-length, so **steps and
all later fields shift**; parse forward (or anchor those fields from block end). Field offsets
relative to `steps`: division +0x2a, scale +0x40, velocity +0x7b, sustain +0xa5, mask +0xe4,
root +0x13f; `steps..block_end` = 0x2b7 bytes (fixed). Track-level vel/sustain/pitch are the
defaults; a per-step lock overrides them for that step.

**⚠️ Steps-region carved into TWO zones (CONFIRMED, iteration1 random-reroll experiment).**
Tool: `t1_blockdiff.py` (aligns blocks to `run`, compares steps-region by `steps`-offset).
Method: one track copied across 4 patterns, re-rolling exactly ONE parameter's random sequence
per copy (per-parameter re-roll; Random amount 0 — the buffer still rewrites). `iteration1.zip`
→ only **51 bytes changed, in 3 runs of exactly 17 bytes**, one per re-rolled param. Findings:
- **Zone A = `steps+0x00 … ~0x150`: live per-track parameter table.** A sequence of
  **`<value (1–2 B)> <17-byte random sequence>`** records, value-FIRST, zero-padded between.
  Re-rolling a parameter rewrites only its 17-byte random run; the value byte stays put.
  Confirmed value→random pairs: **steps**`@+0x00`, **div(u16)**`@+0x2a`, **scale**`@+0x40`,
  **mask(u16)**`@+0xe4`, **root**`@+0x13f`; **Pitch-rnd**`@+0x55`, **Velocity** val`@+0x7b`/
  rnd`@+0x7c`, **Sustain** val`@+0xa5`/rnd`@+0xa6` (vel value byte read 0x64=100, sus 0x3f=63,
  matching the programmed track → these ARE the parameter records). ~8 more 17-byte random runs
  (`+0x16,+0x68,+0x91,+0xbb,+0xd0,+0xfa,+0x110,+0x126`) = the other randomizable params
  (Repeats/Cycles/Rotate/Phrase/Harmony/Chance/Timing/Accent…), each identifiable by re-rolling
  it and seeing which run moves.
- **Zone B = `steps+0x150 … 0x296`: `00 00 00 <id> 00 64 <17 B>` array**, ids `0x46..0x52`
  (terminated by id `0x53` + zero pad). This array **did NOT change on track-param re-roll** →
  it is **not** the track random buffer (likely per-step / "locked random" state). Earlier RE
  mistakenly flagged this as the random region — it is a separate structure.
- **Semantics confirmed:** "copy pattern" **preserves** random sequences (else all runs would
  differ); per-parameter re-roll is **surgical** (one run); re-roll works at Random=0.
- **Implication:** ~15×17 ≈ 255 bytes of Zone A are pure random buffer the importer may clone
  freely; the **value/structure bytes between them** hold the still-undecoded params.

**✅ STYLE decoded (iteration2 Style-sweep, `t1_blockdiff.py --sweep`).** One track (3-note
chord default) copied across 10 patterns with Style = VB1..VB5 then VB9..VB13. **Exactly one
byte changed: `steps+0x13d`**, values `[0,1,2,3,4, 8,9,10,11,12]` = `VB_index − 1`. So:
**Style @ `steps+0x13d`; polyphonic (chord) = 0–4, monophonic (arp) = 8–12; Fixed-poly = 0.**
(Voicing = motion amount, a separate value, not yet located.) The importer should write `0`.

**❌ Style is NOT the chord blocker (hypothesis tested & rejected).** Both the proven-broken
`hwtest/hwtest.t1` and the proven-working `hwtest/hwtest_handtmpl.t1` have **Style=0** on the
chord track. Masking the 29 known random runs, the **only** structural difference between
broken and working chord blocks is a **trailing lock-summary**:

**✅ TRUE chord blocker = trailing per-block LOCK-SUMMARY (steps+0x29c), and it's UI/cursor
state — not structural.** After Zone B's `…53` terminator (steps+0x295), a **lock-bearing**
block carries `01 00 00 00 <K> 00` at `steps+0x29c`, and ends with a `00 01` marker at
`steps+0x2b5/+6` (a non-lock block has this region all-zero and ends `01 00`). Decoded via
iteration3 (samples/14), a 2-pattern bank of identical chord-lock tracks with locks entered in
a controlled order:
- `+0x29c` (**A**) = `1` whenever locks are present (the record exists); `0` = non-lock.
- `+0x2a0` (**K**) = **newest-stored / last-edited lock step** (cursor). All iteration3 blocks
  read K=12 (locks entered 1→5→9→13 → newest = step 13 = 0-based 12). The earlier `samples/11`
  K=8-on-[0,4,8,12] "anomaly" was just hand-edit order.
- end-marker = position value `m` (STRUCTURAL — a wrong value makes the device silently DROP or
  mis-slot the track, hardware-confirmed). It sits at **`steps+0x2b5` on a NON-lock block**
  (`+0x2b6`=0) and at **`steps+0x2b6` on a LOCK block** (`+0x2b5`=0). Synthesis must set the
  right one for **both** kinds — leaving a non-lock block's `+0x2b5` at the template's `1`
  dropped every position-≥2 non-lock track on device (iteration-10-hwtest v1). **Rule (corrected via iter9/iter10, N up to 12): `m = i + 1` for every
  track except the pattern's LAST, which is `1`** (Form Y) — e.g. 8-track pattern =
  `[1,2,3,4,5,6,7,1]`, 12-track = `[1,2,…,11,1]`, 3-track = `[1,2,1]`, 1-track = `[1]`. (The
  earlier `N − i` rule only *coincided* for N ≤ 3, which is all the first hwtest patterns had;
  it is wrong for N > 3.) The bank's final block may instead be Form X (`m = 0`, marker carried
  by the terminator) — see "Final lock block".
  A is `1` whenever locks present (the `samples/11` A=2 final-block case is the Form-X variant,
  below); K is cursor state (any in-range locked step loads).

**Why a lock track loads or drops (all hardware-confirmed):**
1. A lock-bearing block must have the summary **present** (A=1 + the record), not the non-lock
   template's all-zero region. (Old bank cloned a non-lock template → A=0 → whole-bank reject.)
2. A **single-note-default (pc=1)** track must be **fully** pitch-locked or not at all — a
   PARTIAL lock (some pulsed steps left on the default) drops the track. (Chord-default pc≥2
   tracks tolerate partial locks — `handmade2` blk2.) Importer locks every active step once any
   lock is needed.
3. The end-marker `+0x2b6` must equal the position value above, or the track drops.
**Fix (shipped, HARDWARE-VERIFIED):** `midi_to_t1.build_track_block` writes the summary
(A=1, K=max locked step, end-marker = position value passed by `midi_to_pattern`) when a lock
block uses a non-lock template; `map_channel_to_track` locks all active steps when any pitch
lock is needed; skipped for self-templated blocks so roundtrip stays byte-exact.

**⚠️ Final lock block: the `01` end-marker must appear EXACTLY ONCE (device rejects the whole
bank otherwise).** A lock block's tail has a single `01` marker; there are two device-proven
layouts, distinguished by where the marker sits relative to the lock terminator byte:
- **Form Y** (device-authored `iteration3`, all blocks): marker at the region end-byte
  `steps+0x2b6`, lock terminator = `00`, NO multi-pattern pad. Tail `…00 01 00`. Summary A=1.
- **Form X** (`samples/11`, `hwtest_handtmpl`): region end-byte `steps+0x2b6`=`00`, lock
  terminator = `last_tc-1`, +1 pad byte on multi-pattern banks. Tail `…00 00 01 (00)`. Summary
  A=2, `+0x2a1`=4. (The "final terminator = last_tc-1" rule from earlier RE is just Form X.)
The first synthesized bank FAILED on device (whole-bank reinitialise) because the importer set
the marker at `+0x2b6` (Form Y) AND stamped `last_tc-1` at the terminator (Form X) → two
adjacent `01`s. **Fix:** `build_bank` applies the Form-X terminator+pad ONLY when the final
block's region end-byte is 0 (template-cloned/roundtrip); a from-scratch lock block keeps Form Y
(terminator 0, no pad). The regenerated bank now matches `iteration3` byte-for-byte per block
(Form Y); `hwtest/hwtest_locksummary.t1` + `project_locksummary.zip`. **HARDWARE-VERIFIED: a
fully-synthesized bank with single-note, scale, chord, velocity-ramp and sustain tracks across 2
patterns loads and renders correctly on device.**

### Still open (for full-fidelity export)
- scale+root **quantization** of playback (exporter currently emits raw absolute pitch;
  standard scale tables need confirming, esp. Iwato snap direction and "Tetra");
- "free" (non-fixed) division mode; track type (Note/CC/FX); mute/enable;
  per-step overrides (pitch/vel/sustain) + their "override active" flag.

## STEPS up to 64 + CYCLES (DECODED, `iteration9.zip`, 2026-06-21)
Source backup `iteration9.zip` (bank `0.t1`, 20 blocks): Pattern 1 = 8 tracks exercising
**step count 16/32/48/64** + the **step-group page selector**; Pattern 2 = 12 tracks
exercising **cycles** (count 1–16, plus per-cycle edits of pitch / sustain / steps-length /
gate / per-step locks, on single and multiple cycles). Tool: `t1_cycles.py` (in repo).
Manual refs: `…/shape/steps` and `…/shape/cycles`.

### Steps 1–64 — the gate array is a FIXED 64 bytes (CONFIRMED)
The "16-byte gate" was always a **64-byte** region: `run+0x0c … run+0x4c` (0x40 = 64 B), one
byte per step (`01`=pulse). It is step-count-independent — `OFF_LOCKS = run+0x4c` sits exactly
after it, which is why `steps`/division/etc. parsed correctly even for 32/48/64-step tracks.
The old parser only *read* the first 16; **read all 64** (clamp the live range to the `steps`
field). `steps` (track length, **1–64**, default 16) is the `steps+0x00` field as before.
- **Random sequences stay 16 long** regardless of track length (per manual) — Zone-A's
  17-byte runs are unchanged by step count; only the gate widens.
- **Step-group page selector** (UI cursor: which 16-step page is shown) = **`steps+0x2b0`**,
  0-based: `0`=steps 1–16 ([BANK]), `1`=17–32 ([PATTERN]), `2`=33–48 ([TEMP]), `3`=49–64
  ([MUTE]). Proven: Pattern-1 t5–t8 (all 16 steps) read 0,1,2,3 for selector 1/2/3/4. Cursor
  state only — does not affect playback; safe to write 0.

### Cycles 1–16 (default 4) — per-track variation engine (DECODED)
Each track loops through N **cycles**; each cycle can override track-level params and per-step
data. A "default" cycle is unmodified. Storage is split across THREE places in the block:

**1. Cycle COUNT** (1–16, default 4) = **`steps+0x14d`** (u8). CONFIRMED: reads 1,2,3,4,…,16
across Pattern-2 tracks exactly. (Note: the byte at `steps+0x2b5` is the **position end-marker**
documented earlier, NOT the cycle count — they coincided only because tracks 1–4 had cycle
count == track index.)

**2. Per-cycle TRACK-PITCH overrides** — appended **in the header, right after the base pitch
list** (and before the `…0c 00 00 00` separator that precedes `run`):
```
[num_pitch_overrides:u8]  then per override: [cycle_idx:u8 0-based] [pitch_count:u32 LE] [pitch:u8 …]
```
Stored **descending** by cycle index; `pitch_count` supports chords (same encoding as a per-step
pitch lock). CONFIRMED end-to-end:
- cycle1→D3: `… 3c | 01 | 00 01000000 3e` (base C3, 1 override, cyc 0 = D3).
- cycle2&4→D3: `… 3c | 02 | 03 01000000 3e | 01 01000000 3e` (cyc 3 then cyc 1).
- cycle16→D3: `… 3c | 01 | 0f 01000000 3e`.
- cycle8→C3,E3,G3 chord: `… 3c | 01 | 07 03000000 3c 40 43`.
(No override ⇒ a single `00`, which is the normal lock-free header — that `00` is this count.)

**3. Per-cycle STEP-SEQUENCE records + param overrides** — inserted in the **lock region**,
right after the base groove/pitch lock counts (`run+0x4c`,`run+0x4d`) and **before `steps`**
(so `steps` and everything after it shifts later — this is why the old parser returned garbage
on edited-cycle tracks). Layout:
```
run+0x4c  [base groove_lock_count]          ← the existing base-track lock lists
run+0x4d  [base pitch_lock_count]
run+0x4e  [num_edited_cycles:u8]
          num_edited_cycles × per-cycle RECORD (67 B when minimal):
              [cycle_idx:u8 0-based]
              [64-byte gate]                 ← that cycle's own pulse pattern
              [groove_lock_count + groove locks]   ← per-step vel/sustain for this cycle
              [pitch_lock_count  + pitch  locks]   ← per-step pitch/chord for this cycle
          [per-cycle TRACK-PARAM override section]  ← non-pitch track defaults per cycle
          [18-byte pad] [steps] …
```
The per-cycle gate + lock lists reuse the **identical** base-track formats (gate 64 B; groove
lock `[entry_count][step] then n×[param][value][00 00 00]`; pitch lock `[step][count:u32][pitches]`).
CONFIRMED examples:
- cycle16 "steps 1–8": record gate = `01 01 01 01 01 01 01 01 00…` (pulses 1–8).
- cycle1 per-step chord on step1: record's pitch-lock list = `…00(groove=0) 01(pitch=1) 00 03000000 3c 40 43` (step0 → C3,E3,G3).
- cycle2 per-step step1 vel16/sus16: record's groove list = `01 02 00 0e 7f 00 00 00 0a 7f 00 00 00` (1 lock, 2 entries on step0: sustain 0x7f + velocity 0x7f).
- Two edited cycles (block 14) ⇒ two 67-B records back-to-back (`num_edited_cycles=2`),
  cycle indices descending; +67 B of block size per edited cycle.

**Per-cycle TRACK-PARAM override section** (DECODED, `iteration10.zip` dual sweep) — non-pitch
track defaults (steps-length / division / scale / velocity / sustain / root …) that differ for
one cycle, stored at the **start of the 18-byte pad right before `steps`** (all-zero = no
override). It reuses the **groove-lock list format**, keyed by cycle instead of step:
```
[num_records:u8]
   per record: [entry_count:u8] [cycle_idx:u8 0-based]
               then entry_count × [param_id:u8] [value:u16 LE] [00 00]
```
The 5-byte entry is `[param][value:u16][00 00]` — the **value is u16 LE** (proven by a per-cycle
division=/1 → 384 = `80 01`; velocity/sustain just have a 0 high byte, which is why the groove
form historically read as `[param][value:u8][00 00 00]`). **Param-id table** (confirmed; shared
with groove locks — vel/sus ids match):

| id | param | value | id | param | value |
|----|-------|-------|----|-------|-------|
| `0x00` | steps (length) | 1–64 | `0x0a` | velocity | 0–127 |
| `0x04` | division | ticks/step (value×div=384) | `0x0e` | sustain | 0–127 |
| `0x06` | scale | 0=Chrom,1=Maj,… | `0x22` | root | 0=C…11=B |

CONFIRMED bytes (all on cycle 2 except the cycle sweep): `01 01 02 0a 7f 00 00`=cyc3 vel127,
`01 01 01 0e 7f 00 00`=cyc2 sus127, `01 01 01 00 08 00 00`=cyc2 steps8, `01 01 01 04 80 01 00`=
cyc2 div/1 (384), `01 01 01 06 01 00 00`=cyc2 scale Major, `01 01 01 22 02 00 00`=cyc2 root D.
A cycle-index sweep (sustain on cycles 1/2/3/4) read `cycle_idx` = 0,1,2,3 at byte 3. A
pitch-only edited cycle still gets its 67-B gate record but an *empty* (all-zero) param pad
(its pitch lives in the header).

**✅ Cycles decode + SYNTHESIS are COMPLETE.** Header pitch overrides + per-cycle step-seq
records + the param-override section are all confirmed against device backups, and
`midi_to_t1.build_track_block` now *emits* them: `test_roundtrip.py` rebuilds the two
device-authored cycle banks (iteration9, iteration10) **byte-for-byte**, and a fully
from-scratch cycle bank (`make_cycle_hwtest.py` → `cycle_hwtest.t1`) is self-consistent.
Lock-region layout for synthesis (after the base lock lists): `[num_edited_cycles]` then per
cycle `[cycle_idx][64-B gate][groove locks][pitch locks]`, then `[param_num][param records]`,
then a **16-B** pad, then `steps` (the historical "18-B pad" = `num_edited_cycles=0` +
`param_num=0` + 16 zeros). A block has its lock terminator + lock-summary when ANY base **or**
per-cycle record carries per-step locks.

### Open / needs another targeted backup
- ~~param-id table for per-cycle track-param overrides~~ — **DONE** (iteration10, table above).
- ~~base track per-step locks AND cycle records coexisting (the device's natural compact cycle
  encoding: base = cycle 0 with its locks, records only for differing cycles)~~ — **DONE**, device-
  authored `samples/17_base_locks_cycles` (3 tracks: base pitch-locks+record, base groove-locks+
  record, base chords+2 records incl. a track-pitch-only cycle). Rebuilds **byte-for-byte**; decoder
  reads it and `build_track_block` emits it. Also re-confirmed **velocity = N×8** (vel 16 = 2/16 LED)
  and **sustain min=0 / max=127**. `build_cycle_track` now uses this natural encoding.
- ~~The 2-byte tail / end-marker & final-block Form-X/Y rules when cycle records are in the bank's
  last block~~ — exercised by the hardware-verified `make_2mid_cycles` import (final block carried
  cycle records, `final_has_locks=True`, loaded correctly) and the byte-exact `samples/17` rebuild.
- ~~Importer synthesis of cycles (MIDI→.t1)~~ — **DONE**: `midi_to_t1.py --cycles bars` maps each
  voice's consecutive `--steps`-long windows to cycles (window k → cycle k). See `build_cycle_track`.

### Saved pattern cursor — CONFIRMED ISOLATED (`iteration10` banks 1 & 2)
The "which pattern was selected when the backup was saved" cursor is the 0-based pattern **slot**,
stored **only** in the 12-B bank summary: `78 00 00 00 00 <cur> <cur> 01 00 00 00 <cur>` (3 copies
at summary offsets 5,6,11). Proven: two banks identical but for the selected pattern (P2 vs P1)
differed in **exactly those 3 bytes** (`01` vs `00`) — everything else is per-track random state.
It touches no track/pattern content; `build_bank(current_pattern=…)` already emits it. Safe to
set 0.

## Container detail: per-bank `.t1` (CONFIRMED — fully reconstructed byte-exact)
Verified: the 803-byte track block is **byte-identical** between the manual `.t1` and the
autosave files. The whole container is now reproduced byte-for-byte across all 32 sample
banks (`test_roundtrip.py`). Layout of a per-bank `.t1` holding multiple patterns:
```
0x00  05 "2.1.4"                       magic + version (6 B)
0x06  <npat> 00 <tc0> 00 00            bank header: npat=#patterns serialized,
                                       tc0=first-pattern track-count (5 B)
0x0b  P0 track blocks                  tc0 blocks
      ── per following serialized pattern ──
      [8 B end-of-pattern trailer] = 00 00 <prev_tc-1> 00 00 00 00 00
      [4 B next-pattern header]    = <slot> <tc> 00 00
      <tc> track blocks
      ...
      [8 B end-of-last-pattern trailer] = 00 00 <last_tc-1> 00 00 00 00 00
0xEnd [12 B bank summary] 6f 73 7c 74   bank trailer ("os|t")
```
- **`<slot>`** = the device pattern slot (0–15) of the upcoming pattern. Only **used**
  patterns are serialized, so slots can be **sparse** (e.g. `04_pitch_vel_sustain` stores
  slots 0 and 2 = Patterns 1 & 3). The first serialized pattern is implicitly slot 0.
- **`prev_tc-1`** = (track-count of the pattern that just ended) − 1.
- **Bank summary (12 B):** `78 00 00 00 00 <cur> <cur> 01 00 00 00 <cur>` where `<cur>` is
  the **saved cursor** — the pattern slot selected when the backup was taken (user state, not
  derivable from content; the device opens the bank on it). 0 is always valid.
- A lock-bearing block's extra terminator byte (see above) lands inside these gaps, so the
  pattern-boundary gap measures 12 (lock-free last block) or 13 (last block has locks).

Autosave equivalent: one hash-named file per pattern (header `<tc> 00 00` + blocks +
12 B `…os|t` trailer), a constant 14 B global file `05 "2.1.4" 00 00 00 00 os|t`, and (with
2+ patterns) a 22 B index file whose payload equals the per-bank trailer/bank-summary.

## Reference dump: single-track per-bank `.t1` (e.g. `1.t1`, 838 bytes)

| Offset        | Size | Meaning | Status |
|---------------|------|---------|--------|
| `0x00`        | u8   | length of version string (`0x05`) | confirmed |
| `0x01`–`0x05` | 5    | ASCII firmware version `"2.1.4"` | confirmed |
| `0x06`        | u8   | **npat** (#patterns serialized; 0=empty bank). `0x08`=tc0 (first-pattern track-count). For single-pattern banks both read alike. | confirmed |
| `0x07`–`0x22` | 28   | fixed skeleton / counts (see below) | partial |
| `0x23`–`0x32` | 16   | **STEP / GATE array** — 1 byte per step, `0x01`=pulse, `0x00`=empty | confirmed |
| `0x33`–`0x76` | 68   | zero padding | confirmed |
| `0x77` … tail | ~640 | per-track **stored "random sequence"** region (high entropy, stable) | open |
| tail (15 B)   | 15   | footer: `78 00 00 00 00 00 00 01 00 00 00 00 6f 73 7c 74` (`"os|t"`) | confirmed |

### Header skeleton `0x07`–`0x22`
```
0x07: 00 01 00 00 0c 00 01 00 00 00 3c 00 0c 00 00 00
0x17: 00 01 02 03 04 05 06 07 08 09 0a 0b
```
- `0x0b = 0x0c = 12`, `0x11 = 0x3c = 60`, `0x13 = 0x0c = 12` — counts/lengths, TBD.
- `0x17`–`0x22` = the run `0,1,2,…,11` (12 bytes) — purpose TBD (default scale row? index map?).
- All of `0x07`–`0x22` is **constant** across the 8 pulse-test banks.

### STEP / GATE array — CONFIRMED
16 bytes at `0x23`. One byte per step. `0x01` = active pulse, `0x00` = empty.
Proven against banks with 0..7 pulses on steps 1..N of Pattern 1 / Track 1:
```
1.t1: 01 00 00 00 ...   (pulse on step 1)
7.t1: 01 01 01 01 01 01 01 00 ...   (pulses on steps 1-7)
```

### Empty bank (`0.t1`, 0 pulses) — 23 bytes
`05 "2.1.4" 00` + `78 00 00 00 00 00 00` + `01 00 00 00 00` + `"os|t"`.
The ~838-byte payload only materialises once a track has content; the trailer here matches
the footer of full banks.

### Random-sequence region `0x77`…tail — OPEN
Repeating ~23-byte records `00 00 00 <id> 00 64 <17 high-entropy bytes>`, ids `0x46`..`0x53`.
Stable per bank but unique per bank/track (each track has its own fixed sequence). Differences
between `1.t1`..`7.t1` here are due to them being different banks, **not** the pulse edits.
Likely the generative engine's stored state; probably not needed for note-level MIDI export.

## Data model (from manual)
16 banks → 16 patterns → 16 tracks → up to 16 steps. Per track: **Shape** (steps, pulses,
rotate, cycles, division, repeats…), **Groove** (velocity, probability, sustain, accent,
timing), **Tonal** (up to 8 pitches, scale, root), **Setup** (MIDI channel & output).
The current test files exercise only Pattern 1 / Track 1, so only that track's storage is
visible so far.

## Still to decode
pitch encoding, velocity, sustain/length, per-pattern stride, per-track stride, MIDI channel,
shape params (steps/pulses/rotate/division), per-step overrides. See the plan's RE campaign.
