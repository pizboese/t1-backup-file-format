# Torso T-1 `.t1` backup format — reverse-engineering notes

Status: **in progress**. Firmware `2.1.4`. One `.t1` file = one **bank**.
Format is a flat, **deterministic** byte serialization (re-exporting unchanged content
yields byte-identical files — verified across all 8 banks).

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

**Groove locks (CONFIRMED, iteration 8):**
```
[num_groove_locks:u8]  then per lock (7 B):  [entry_count:u8][step:u8 0-based][param:u8][value:u8][00 00 00]
```
param `0x0a`=velocity, `0x0e`=sustain; value 0–127. Verified: step5 vel=40, step6 vel=88,
step8 sus=16, step9 sus=120 (all matched device LEDs).

**Region layout (CONFIRMED):** after the 16-byte gate, at `run+0x4c`:
`[groove list][pitch list][18 B pad][steps]`. The lists are variable-length, so **steps and
all later fields shift**; parse forward (or anchor those fields from block end). Field offsets
relative to `steps`: division +0x2a, scale +0x40, velocity +0x7b, sustain +0xa5, mask +0xe4,
root +0x13f; `steps..block_end` = 0x2b7 bytes (fixed). Track-level vel/sustain/pitch are the
defaults; a per-step lock overrides them for that step.

### Still open (for full-fidelity export)
- scale+root **quantization** of playback (exporter currently emits raw absolute pitch;
  standard scale tables need confirming, esp. Iwato snap direction and "Tetra");
- "free" (non-fixed) division mode; track type (Note/CC/FX); mute/enable;
  per-step overrides (pitch/vel/sustain) + their "override active" flag.

## Container detail: per-bank `.t1` (CONFIRMED via 5-block manual backup)
Verified: the 803-byte track block is **byte-identical** between the manual `.t1` and the
autosave files. Layout of a per-bank `.t1` holding multiple patterns:
```
0x00  05 "2.1.4"                       magic + version (6 B)
0x06  <tc0> 00 <npat> 00 00            first-pattern header: tc0=P0 track-count,
                                       npat=number of patterns in bank (5 B)
0x0b  P0 track blocks                  tc0 x 803 B
      ── per following pattern ──
      [8 B end-of-pattern trailer]     mostly zeros (a non-zero byte seen at +2)
      [4 B pattern header] = <pat_idx> <tc> 00 00
      <tc> track blocks                tc x 803 B
      ...
      [8 B end-of-pattern trailer]
0xEnd 78 00 00 00 <bank summary...> 6f 73 7c 74   bank trailer ("os|t")
```
Block deltas in the 5-block sample: `803, 803, 815, 815` — the `815` (=803+12) gaps are the
pattern boundaries (12 B = 8 B trailer + 4 B next-pattern header).

Autosave equivalent: one hash-named file per pattern (header `<tc> 00 00` + blocks +
12 B `…os|t` trailer), a constant 14 B global file `05 "2.1.4" 00 00 00 00 os|t`, and (with
2+ patterns) a 22 B index file whose payload equals the per-bank trailer/bank-summary.

## Reference dump: single-track per-bank `.t1` (e.g. `1.t1`, 838 bytes)

| Offset        | Size | Meaning | Status |
|---------------|------|---------|--------|
| `0x00`        | u8   | length of version string (`0x05`) | confirmed |
| `0x01`–`0x05` | 5    | ASCII firmware version `"2.1.4"` | confirmed |
| `0x06`        | u8   | **track-count** (0=empty; increments per serialized track block) | confirmed |
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
