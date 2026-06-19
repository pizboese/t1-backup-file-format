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
- `+0x2b5/+0x2b6` = end-marker (`00 <m>`). **`+0x2b6` (m) is STRUCTURAL, position-dependent —
  NOT cosmetic** (a wrong value makes the device silently DROP that track on load,
  hardware-confirmed). Rule from device banks: `m = 1` for the first track of a pattern, else
  `N - i` (N tracks, index i) → 3-track pattern = `[1,2,1]`, 2-track = `[1,1]`, 1-track = `[1]`.
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
