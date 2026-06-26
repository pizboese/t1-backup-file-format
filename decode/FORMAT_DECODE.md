# Complete-decode scoreboard + notes

Live working doc for the campaign (branch `completeDecode`). The canonical, stable reference stays
`FORMAT.md` at the repo root — a finding moves there only once confirmed (sample rebuilds
byte-for-byte in `decode/test_decode.py` **and** parser reports the programmed ladder).

Status: ✅ DECODED (located + synthesized) · 🟡 PARTIAL (located, gaps) · ❌ UNDECODED.
Offsets are relative to the `steps` field unless noted. `(B1)` = decoded in backup-1
(`samples/20_backup1_params`, already canonical in `FORMAT.md`).

## Scoreboard — drives the work order (import-critical → Shape → Groove/Tonal → Modes/Routing)

### Shape
| Feature | Range | Status / location |
|---|---|---|
| Steps | 1–64, def 16 | ✅ `steps+0x00`; 64-B gate @ `run+0x0c` |
| Pulses (count) | 1–steps | 🟡 `steps+0x15` u8 (count 1→16) — located B21 |
| Rotate | directional | 🟡 `steps+0x13a` u8 — located B21 (sign unconfirmed) |
| Cycles | 1–16, def 4 | ✅ `steps+0x14d`; per-cycle engine decoded |
| Division | note values; Free | ✅ `steps+0x2a` u16 + free-flag `steps+0x299` (B1) |
| Repeats | 0–48 (+∞) | 🟡 `steps+0xfa` u8 (stored repeats+1) — located B21 |
| Ramp | directional | 🟡 `steps+0x13b` s8 bipolar — located B21 (scale provisional) |
| Time (repeat spacing) | note values | 🟡 `steps+0x124` u16 + free-flag `steps+0x29a` — located B21 |
| Pace | bipolar | 🟡 `steps+0x13c` s8 — located B21 (scale provisional) |
| Voicing (amount) | continuous | 🟡 `steps+0xcf` s8 — located B21 (distinct from Style) |
| Voicing (note direction) | Up / Down | 🟡 `steps+0x149` u8 0=Up/1=Down — located B27 (2-block) |
| Style | poly 0–4 / mono 8–12 | ✅ `steps+0x13d` |
| Range | amount | 🟡 `steps+0x90` s8 — located B21 (1 noise collision) |
| Phrase (shape+length) | 8 shapes; 1–64 bars | 🟡 shape `steps+0x147` enum (0–7 shapes, 8=CV-in) — located B21; length `steps+0x144` enum `v→2^(6−v)` bars (B26) |

### Groove
| Feature | Range | Status |
|---|---|---|
| Velocity (track+step) | 0–127, 1:1 | ✅ `steps+0x7b`; lock id `0x0a` |
| Probability | bipolar | ✅ `steps+0x79` s8 (B1) |
| Sustain (track+step) | 0–127, def 64 | ✅ `steps+0xa5`; lock id `0x0e`; log law |
| Timing (swing) | bipolar, x1/x2/x4 | ✅ amount `steps+0xba` s8; sub `+0x146` (B1) |
| Delay | bipolar | ✅ `steps+0x13e` s8 (B1) |
| Accent (amount) | bipolar | ✅ track `steps+0x10f` s8 ±20; step-lock id `0x18` (B22) |
| Groove (pattern+length) | 8 patterns; 1–64 bars | 🟡 pattern `steps+0x148` enum (0–7, 8=CV-in) (B22); length `steps+0x145` enum `v→2^(6−v)` bars (B28) |

### Tonal
| Feature | Range | Status |
|---|---|---|
| Pitch (track+step+cycle) | absolute, C3=60 | ✅ header + locks + cycle overrides |
| Harmony | hysteretic | 🟡 value `run−0x10` u8 0–15 + rewrites pitch list (B22) |
| Scale | presets + user | ✅ `steps+0x40` 0=Chrom…6=Tetra, 7=Custom; user note-set = degree table (B22) |
| Root | C–B (0–11) | ✅ `steps+0x13f` |

### Setup / Global
| Feature | Range | Status |
|---|---|---|
| Length (track loop) | 1/64–16 bar, ∞ | ✅ `steps+0x14b` enum 0–15 (B1) |
| Quantize (per-pattern) | bar divisions | ✅ pattern-trailer 4th byte (B1) |
| Channel | 1–16 | ✅ out-mask `steps+0xe4` |
| Output (internal routing) | per-track 16-track bitmask | ✅ `steps+0x297` u16 LE, bit i = route to track i+1 (B23) |
| Tempo (per-bank) | 24–280, def 120 | ✅ bank summary bytes 0–1 u16 LE (B1) |
| Random intensity (per-track) | 1/16–16/16 | ✅ `steps+0x140` u8, LED N×8 scale 0–127 (B24) |
| Random amount (per-param) | ±20 bipolar | ✅ s8 at `value+0x12` for each sequenced param — full 16-param map (B24) |
| Random slew (per-param) | 0–~127 | ✅ u8 at `amount+1` (= `value+0x13`); Steps measured 0/1/21/78 (B24) |
| Random lock (per-param) | on/off | ✅ u8 0/1 at `amount+2` (= `value+0x14`); 13/16 params confirmed (B24) |
| Random phase (per-param) | step shift | ✅ NO byte — left-rotation of the 16-byte modulation sequence `value+0x01..+0x10` (B24) |
| Rate | advance speed | ✅ `steps+0x141` u16 LE, note-value (val×div=384) (B23) |

### Tracks / Modes
| Feature | Status |
|---|---|
| Track Mode Note/CC/FX | ✅ `steps+0x154` u8 enum 0=Note/1=CC/2=FX (B23) |
| CC encoder value | ✅ `steps+0x155` + 0x17·N (14 encoders, def 100); per-step lock id `0x80` (B23) |
| CC encoder select (=CC#) | 🟡 enable flag `steps+0x16b`+0x17·N; default CC#=70+N; custom CC# not in B23 |
| FX config | ✅ none — identical to Note block, only mode=2 (B23) |
| Mute / enable | ✅ mute flag `run−0x0d` (block-header byte before pitch marker): 1=muted (B23) |

### Zone-A random runs (16 sequenced params, one 16-B mod-sequence each) — ✅ ALL RESOLVED (B24)
Each sequenced param is a self-describing record: `value | 16-B modulation sequence (value+0x01..+0x10)
| tail | amount(value+0x12) | slew(+0x13) | lock(+0x14)`. The "17-B Zone-A run" = `value` + its 16-B
sequence. All 8 formerly-unidentified runs are now named (B24): `+0x16`=Pulses, `+0x68`=Pitch-region,
`+0x91`=Range, `+0xbb`=Sustain-region, `+0xd0`=Voicing, `+0xfa`=Repeats, `+0x110`=Accent, `+0x126`=Time.
Phase = a left-rotation of the 16-B sequence (no stored byte). See the B24 decode-log entry for the
full per-param amount-offset map.

## Campaign backups (fill as acquired → `decode/samples/NN_*`)
| # | Theme | Params targeted | Sample | Status |
|---|---|---|---|---|
| 1 | import-critical timing/feel | Timing/Delay/Length/Quantize/FreeDiv/Probability + per-bank Tempo | `samples/20_backup1_params` (root) | ✅ done (canonical) |
| 2 | Shape + Repeater | Pulses, Rotate, Repeats, Ramp, Time, Pace, Range, Phrase, Voicing-amt | `samples/21_shape_repeater` | ✅ located (B21) |
| 3 | Groove + Tonal | Accent, Groove, Harmony, full Scale table + user scale | `samples/22_groove_tonal` | ✅ located (B22) |
| 4 | Modes + Routing + Global | Note/CC/FX mode, CC#/value, FX, Output routing, Mute, Random amt/Rate | `samples/23_modes_routing_global` | ✅ located (B23) |
| 5 | Random behaviour | Random intensity/amount/slew/lock/phase/rate (16-param map) | `samples/24_random` | ✅ located (B24) |
| 6 | Extras | Phrase-len, Groove-len, Voicing-dir, Repeat choke/tail | `samples/25–28_*` | ✅ located (B25–28) |

## Per-field decode log
(Append a dated entry per field as it flips to ✅: offset, kind, how isolated, sample, rebuild proof.)

### 2026-06-26 — Bank 21 (Shape + Repeater) monotonic-ladder decode
Source: `decode/samples/21_shape_repeater/21_shape_repeater.t1` (9 patterns × 16 contiguous
blocks; P n = blocks 16·(n−1)…16·n−1) + `rotate_fixedsteps.t1` (9 blocks) for Rotate. Method:
align each block to its `steps` field (`decode/_scan_mono.py`, `_scan2.py` — strict ±1, signed-s8
wrap, u16-LE, and Kendall-tau rankers), flag the offset whose 16 values match the programmed
ladder. Offsets are steps-relative. All distinct from the known-offset list.

| Param | Offset | Kind | Evidence (values across the ladder blocks) | Confidence |
|---|---|---|---|---|
| Pulses (count) | `+0x15` | u8 | P1 blk0–15 = `1,2,…,16` (Euclid pulse count 1→16); adjacent Zone-A `0x16` | high |
| Rotate | `+0x13a` | u8 (s8?) | `rotate_fixedsteps` blk0–7 = `0,1,…,7` (gate rotates +1/blk); blk8 is an unrelated ch9/empty track | high |
| Repeats | `+0xfa` | u8 | P3 blk32–47 = `1,2,…,16` = repeats(0→15)+1 (stored as “plays”); lands exactly on Zone-A `0xfa` | high |
| Ramp | `+0x13b` | s8 (bipolar) | P4 blk48–63 = `−20,−19,…,−6` then `+20` (valueCoarseFine sweep); isolated byte (`0x13a/0x13c`=0) | high (offset); med on last-notch +20 jump |
| Time | `+0x124` | u16 LE | P5 blk64–75 = `384,192,96,48,24,12,6,128,64,32,16,8` (note-values, value×divisor=384, same law as division); blk76–79 “free” raw `37,29,16,11` with **free-mode flag `+0x29a`=1** (analogue of div free-flag `+0x299`); near Zone-A `0x126` | high |
| Pace | `+0x13c` | s8 (bipolar) | P6 blk80–95 = `−20,…,−6` then `+20` (same sweep as Ramp); isolated byte | high (offset) |
| Range | `+0x90` | s8 (bipolar) | P7 blk96–111 = `−20,…,−6` then `+20`; one collision (blk105=3, noise); neighbours `0x91/0x92` constant; adjacent Zone-A `0x91` | medium-high |
| Phrase (shape) | `+0x147` | u8 / enum | P8 blk112–119 = `0,1,…,7` (8 shapes); blk120 “CV input” = `8` (only non-positional diff vs base); blk121–127 empty=0 | high |
| Voicing (amount) | `+0xcf` | s8 (bipolar) | P9 blk128–143 = `−20…−9, −7,−6,−5, +20` (skips −8 once — single-notch user slip); neighbours constant; adjacent Zone-A `0xd0`; distinct from Style `+0x13d` | high |

Notes:
- **Param cluster** `+0x13a Rotate · 0x13b Ramp · 0x13c Pace · 0x13d Style · 0x13e Delay · 0x13f Root`
  — Rotate/Ramp/Pace are three adjacent value bytes just before the already-known Style/Delay/Root.
- **Zone-A corroboration**: each value byte sits on/next to a Zone-A run — Pulses↔`0x16`,
  Repeats↔`0xfa`, Range↔`0x91`, Time↔`0x126`, Voicing↔`0xd0` — supporting the “value near its run” hypothesis.
- **P8-T9 “CV input”**: NOT a separate flag — it is simply phrase-shape enum value **8** at `+0x147`
  (`0–7` = shapes 1–8, `8` = CV input). The only other diff on that block is the positional end-marker `+0x2b5`.
- **Bipolar valueCoarseFine** (Ramp/Pace/Range/Voicing): all stored as a single s8 over roughly
  −20…+20; the user’s identical knob-sweep produced `−20…−6` then a jump to `+20` on the last track
  (so the extreme-positive notch is observed but the mid-positive range was not swept — scale of the
  positive half is provisional).

Open/uncertain: exact bipolar scale/granularity (only −20…−6 and +20 observed; coarse vs fine step
size unconfirmed); whether Rotate is signed (only 0…7 seen, all non-negative); Time “free” raw-value
law for T13–16 (`37,29,16,11` not yet mapped to a tick formula); none rebuild-proofed yet (located only).

### 2026-06-26 — Bank 22 (Groove + Tonal) decode + CUSTOM SCALE structure
Source: `decode/samples/22_groove_tonal/22_groove_tonal.t1` (project.zip bank 1). Patterns and the
parser block map: P1 Accent = blk0–15 (chord C-E-G, accent laddered bipolar); P2 Groove = blk16–24
(T1-8 = patterns 1→8, T9 = CV-in); P3 Harmony = blk25–40 (laddered 0→15); P4 Scale presets =
blk41–48; **custom scales T9–16 in the un-parsed gap** after blk48; P6 Accent step-locks = blk49;
P7 Range step-locks = blk50. Method: run-aligned varying-offset dumps (`decode/_scan2.py` + ad-hoc).

| Param | Offset | Kind | Evidence | Confidence |
|---|---|---|---|---|
| **Accent** (track) | `steps+0x10f` | s8 bipolar | blk0–15 = `−20,−19,…,−6,+20` (blk9=+3 noise collision); valueCoarseFine like B21 Ramp/Pace; adjacent Zone-A `0x110` | high |
| **Accent** (per-step lock) | lock id `0x18` | s8 ±20 | blk49 groove-locks `{5:−20, 9:0, 13:+20}` (236/0/20); same ±20 scale as the track byte ✔ cross-check | high |
| **Groove pattern** | `steps+0x148` | u8 enum | blk16–24 = `0,1,…,7,8`: 0–7 = patterns 1–8, **8 = CV input** (mirrors phrase-shape `+0x147`) | high |
| **Harmony** | `run−0x10` u8 **+ pitch rewrite** | u8 0–15 | blk25–40 byte@run−0x10 = `0,1,…,15` AND the stored pitch list is reharmonised per step (see note) | high |
| **Scale** preset enum | `steps+0x40` | u8 | 0=Chromatic 1=Major 2=Minor **3=Penta 4=Hira 5=Iwato 6=Tetra 7=Custom/User** (extends past 6) | high |
| **Custom scale note-set** | scale-degree table (= the `find_runs` landmark) | `count:u32 LE` + `count` semitone bytes (0–11, ascending) | T9–16 = `[0]`,`[0,2]`,`[0,2,4]`,`[0,2,4,5]`,`[1,3,6,8,10]`,`[0,2,4,5,7,9,11]`,`[0,4,7]`,`[0,1,2,3,4]` — match the programmed C / C+D / … / blacks / whites / C+E+G / C..E exactly | high |
| **Range** (per-step lock) | lock id `0x0c` | s8 ±20 | blk50 groove-locks `{5:−20, 9:0, 13:+20}` (236/0/20) | high |

**Custom-scale structure (the structural novelty).** The 12-byte run `00 01 02 … 0b` that
`t1_format.find_runs` treats as the block landmark is **not a magic marker — it is the track's
SCALE-DEGREE TABLE in its default (chromatic) state**: a `count:u32 LE` (=12) followed by `count`
ascending semitone bytes (`0..11`). A **custom/user scale** (`steps+0x40 == 7`) rewrites this table
to list only the enabled semitones (e.g. C+E+G → count 3, degrees `[0,4,7]`). That destroys the
identity run, so `find_runs` silently skips the block — which is why bank 22's 8 custom-scale tracks
sit in a ~7 KB un-parsed gap (between blk48 run `0x970b` and blk49 run `0xb310`). **Preset scales
(enum 1–6) keep the identity table** — the enum alone selects a firmware degree map; the explicit
table matters only when enum == 7. blk48 (T8 “all notes”) is itself a custom (enum 7) whose table
happens to equal chromatic `[0..11]`, so its landmark survived and the parser found it. Decoder +
verification in `decode/custom_scale.py` (`find_scale_tables()` locates every table by the
`<count u32><ascending semitones>` shape after the `3c`/pitch header, landmark-independent).

**Harmony behaviour.** Harmony is BOTH a stored value byte (`run−0x10`, monotonic 0→15) AND it
**rewrites the stored pitch list** — the device bakes the reharmonised notes into each track's
pitches (blk25 `[60,64,67]`, blk26 `[68]`, blk28 `[61,65,68]`, …, climbing). So it is not a simple
post-`run` ladder byte; an importer must write the value AND the reharmonised pitches. (`run−0x10`
sits in the small pre-pitch header; the offset is robust for ≤3 stored pitches, where the pitch list
is right-anchored just below `run`.)

Open/uncertain: (1) Accent/Range positive-half granularity (only −20…−6 and the +20 extreme seen,
as in B21); (2) Harmony value byte at `run−0x10` not yet rebuild-proofed and its offset is
header-relative (could shift with larger pitch lists); (3) the name of scale enum index 7 beyond
“Custom/User”, and whether presets >6 exist on newer firmware; (4) custom-scale tracks break
`find_runs` — the shipped parser cannot see them (documented, not fixed, per scope).

### 2026-06-26 — Bank 23 (Modes + Routing + Global) decode
Source: `decode/samples/23_modes_routing_global/23_modes_routing_global.t1` (project.zip bank 2).
The shipped parser **desyncs** (reports 94 runs, ~4788-B gap after parser-block 5); pattern
segmentation was done by raw analysis (helpers: `decode/_allblocks.py`, `_p1modes.py`,
`_groupvary.py`, `_runvary.py`, `_blkdiff3.py`). **Pattern map** (find_runs block indices →
programmed pattern): P1 Mode = parser-P0 (5 chromatic blocks) **+ 5 non-chromatic "gap" blocks**
(0xfba,0x12d2,0x15ec,0x1907,0x1c25) = 10 serialized tracks; P2 CC = idx 5–20; P3 CC-lock = idx 21;
P4 FX = idx 22–29; P5 routing = idx 30–45; P6 mute = idx 46–61; P7 random-amount = idx 62–77;
P8 random-rate = idx 78–93. (10+16+1+8+16+16+16+16 = 99; the 6 missing = P1's 6 Note tracks, left
at full default and **not serialized** — Note is the default mode.)

| Param | Offset / id | Kind | Evidence (across the laddered/aligned blocks) | Confidence |
|---|---|---|---|---|
| **Track Mode** Note/CC/FX | `steps+0x154` | u8 enum | P1's 10 serialized tracks (Note tracks omitted) alternate CC/FX → `[1,2,1,2,1,2,1,2,1,2]`; cross-pattern: CC(P2)=**1**, FX(P4)=**2**, Note(P5–P8)=**0** | **high** (triple-confirmed) |
| **CC encoder value** | `steps+0x155` + `0x17`·N | u8 0–127 | P2 T1–8 enc0=`[0,16,24,32,40,48,56,64]` (1/16→8/16 sweep); T9–16 enc1 same; disabled-default = **100**. Array of **14 encoders** stride `0x17` fills `+0x155`…`+0x296`, ending exactly at the routing mask `+0x297` | **high** |
| **CC encoder select** (= which CC#) | enable flag `steps+0x16b` + `0x17`·N | u8 0/1 | P2: enc0 enabled (=1) for T1–8, enc1 enabled for T9–16; the enabled encoder index N ⇒ CC# = **70+N** by default (T1–8=CC#70, T9–16=CC#71 as programmed) | med-high |
| **CC per-step lock** | lock id `0x80` (128) | u8 0–127 | P3 block groove-locks `{step5→0, step9→64, step13→127}` (programmed CC 16/64/112; mid exact, ends LED-quantized) | high (id); med (value scale) |
| **FX config** | — (no extra field) | — | P4 FX blocks are byte-structurally **identical to Note** blocks (pitch list, euclid pulses on T1–4, chords) — only `+0x154`=2 differs. "FX = Note layout, pitch from input" confirmed | high |
| **Internal routing mask** | `steps+0x297` | u16 LE | P5 bit *i* = route→track *i*+1: T5→1=`0x0001`, T8→4=`0x0008`, T11→1234=`0x000f`, T12→12345=`0x001f`, T13→{8,16}=`0x8080`, T14→16=`0x8000`, T15→{1,8,9,16}=`0x8181`, T16→1=`0x0001` — **all 16 match exactly**. Distinct from out-channel mask `+0xe4` | **high** |
| **Mute flag** | `run−0x0d` (block-header byte just before the `0c 00 <pc>…` pitch marker) | u8 0/1 | P6 = `[1,1,1,1,1,1,1,1, 0,0,0,0,0,0,0,0]` — tracks 1–8 muted, 9–16 unmuted, exactly as programmed | high |
| **Random amount** (per-param) | `steps+0x8d` | u8 (0–~20) | P7 (amount→velocity) ladder `[0,1,2,…,12, 0,13,20]`: first 13 tracks clean 0→12; last 3 anomalous (user slip; 20 = coarse-max). Sits right after velocity's 17-B Zone-A random buffer (`+0x7b`+0x12) | medium |
| **Random rate** | `steps+0x141` | u16 LE | P8 = `1/1,1/2,1/4,1/8,1/16,1/32,1/64,1/3,1/6,1/12,1/24,1/48`, T13–16 default `1/16` — note-value law (value×divisor=384) like Division/Time. **Exact match** | high |

**Structural divergence / parser-desync cause (corrects the brief's hypothesis).**
The desync is **NOT** caused by CC/FX mode. P2's 16 CC tracks and P4's 8 FX tracks all retain the
chromatic 12-entry scale-degree table and parse fine. The mode itself is just one byte
(`steps+0x154`); CC/FX blocks are the **same length and layout** as Note blocks (a CC track simply
uses its always-present 14-encoder array `+0x155…+0x296`, which Note/FX tracks carry too, all
default 100/disabled). Two unrelated things break the parser on this bank:
1. **5 of P1's tracks (slots 9,11,12,14,15) carry non-chromatic scale-degree tables**
   (`[0]`, `[0,2,4]`, `[0,2,4,5]`, major-7, `[0,4,7]`) — the **same mechanism as bank 22's custom
   scales**: a table ≠ chromatic-12 destroys the `00 01 02..0b` landmark, so `find_runs` skips the
   block. These 5 fall into the "4788-B gap". The split is **by slot (≤8 chromatic, ≥9 custom)**,
   NOT by CC vs FX — so it looks like pre-existing/leftover scale state on tracks 9–16, unrelated to
   the modes test (see open question).
2. **P1's 6 Note-mode tracks (1,4,7,10,13,16) are not serialized at all** (Note is the default;
   a fully-default track is omitted), so P1 has only 10 serialized blocks of the 16 programmed.

Anchoring the non-landmark blocks via the Zone-B `00 00 00 53 00` terminator (`steps+0x295`)
re-aligns them; that is how P1's mode ladder was read. **The encoder array end (`+0x155`+14·`0x17`
= `0x297`) coincides exactly with the routing mask offset**, a strong cross-check on both the
`0x17` stride and the routing-mask location.

Open/uncertain:
- **CC number is implicit here** — only encoder *select* (enable flag) + default mapping (CC#=70+N)
  are observable; the literal custom CC# byte is not exercised (defaults used). Needs a follow-up
  backup that reassigns an encoder's CC# (as the brief anticipated).
- **Random-amount** offset `+0x8d` rests on a 13-track clean ladder; last 3 tracks anomalous (likely
  user entry). Whether amount is truly per-param (one slot per groove param) or a single track field
  is unconfirmed — only the velocity-targeted slot was swept. Range likely 0–20 (coarse-max 20).
- **CC per-step lock value scale** (0/64/127 vs programmed 16/64/112) is LED-quantized; id `0x80` is solid.
- **P1 tracks 9–16 custom scales**: owner asked (2026-06-26) — **origin unknown / not recalled**, so
  treat as incidental pre-existing scale state (not part of the modes test). It is the actual reason
  this bank desyncs; the modes finding itself (`+0x154`) is unaffected.
- None rebuild-proofed yet (located only; the bank does not roundtrip through the shipped parser).

### 2026-06-26 — Bank 24 (Random behaviour) — full per-param random-control region

Source: `decode/samples/24_random/24_random.t1` (project.zip bank 3). 8 patterns × 16 **contiguous**
tracks = 128 blocks; **P n = blocks 16·(n−1)…16·n−1** (P1=0-15 … P8=112-127). Bank roundtrips OK.
Helpers added under `decode/`: `_rand_dump.py` (steps-relative value dump + non-decreasing flag),
`_rand_pairs.py` (min/max **pair**-signature detector: one offset nonzero only on blocks 2p,2p+1
with opposite signs), `_rand_flag.py` (sparse small-toggle detector for lock/phase/slew). All align
via `t1_blockdiff.collect` (landmark `run` → each block's own `steps`).

**THE STRUCTURE (the prize).** Every *sequenced* parameter carries a self-contained random-control
record anchored at its stored **value** offset:

```
value+0x00            param value (e.g. Steps=16, Velocity=…)
value+0x01 .. +0x10   16-byte random MODULATION SEQUENCE  ← PHASE = left-rotation of this run
value+0x11            tail byte (0xD9 for Steps; NOT constant across params — see caveat)
value+0x12            random AMOUNT   s8, bipolar, full-scale ±20  (min=−20, max=+20)
value+0x13            random SLEW     u8, 0..~127 (non-linear: 0/little/more/max = 0,1,21,78)
value+0x14            random LOCK     u8, 0/1
```

So **amount/slew/lock are 3 contiguous bytes** sitting **immediately after the param's 16-byte
modulation run** — confirming the brief's "amount byte right after each Zone-A buffer" hypothesis
(the old "17-byte Zone-A run" = `value` + the 16-byte sequence). **Phase is NOT a stored byte**: the
device realises it by rotating that 16-byte sequence one step per phase unit (manual: "Phase shifts
the modulation sequence by one step") — proven below.

> **Caveat (main-session spot-check, 2026-06-26):** the `value+0x11` tail byte is `0xD9` **only for
> Steps**; for other params it varies (velocity=`0xc7`, sustain=`0xc6`, …) — it is NOT a constant
> separator, it's just the last byte of each param's modulation region. This does NOT affect the
> amount map: all 16 amount offsets below were **directly measured** from the P2/P3 min/max pairs
> (and independently re-verified in the main session — every pair reads exactly −20/+20 at the listed
> offset, incl. Cycles `+0x14e` and Division `+0x3d`), not derived from a fixed value-gap.

| Programmed (pattern) | Field | Offset | Kind | Evidence | Confidence |
|---|---|---|---|---|---|
| P1 track Random INTENSITY | per-track master | `steps+0x140` | u8 | blk0–15 = `0,16,24,32,…,120,127` (1/16→16/16, LED N×8); 0 in all other patterns; sits just before Rate `+0x141` | **high** |
| P2/P3 per-param AMOUNT | s8 ±20 | `value+0x12` (see map) | s8 | each min/max pair → one offset `[…,−20,+20,…]`, 0 elsewhere — 16/16 params isolated cleanly (`_rand_pairs.py`) | **high** |
| P4 per-param LOCK | u8 0/1 | `amount+2` (`value+0x14`) | u8 | flag=1 **only in P4**, one param per track, exactly at amount+2; 13/16 confirmed | **high (structure)** |
| P5 Steps PHASE | rotation (no byte) | `value+0x01..+0x10` | — | T1–8 = phase 0–7: the 16-byte Steps run is the SAME sequence rotated **left by phase** (perfect diagonal); amount stays max=20 on all 8 | **high** |
| P6 Steps SLEW | u8 | `value+0x13` (= amount+1) | u8 | blk80–83 (zero/little/more/max) = `0,1,21,78`; default 0 on T5–16; sits between amount and lock | **high (Steps)** |

**Per-param AMOUNT map** (amount = `value+0x12`; slew = +1; lock = +2). Offsets are steps-relative.

| Param | value off | amount | slew | lock | gap(amt−val) |
|---|---|---|---|---|---|
| Steps | +0x00 | **+0x12** | +0x13 | +0x14 | 0x12 |
| Pulses | +0x15 | **+0x27** | +0x28 | +0x29 | 0x12 |
| Division (u16) | +0x2a | **+0x3d** | +0x3e | +0x3f | 0x13 |
| Pitch | +0x55 | **+0x66** | +0x67 | +0x68* | 0x11 |
| Velocity | +0x7b | **+0x8d** | +0x8e | +0x8f | 0x12 |
| Sustain | +0xa5 | **+0xb7** | +0xb8 | +0xb9 | 0x12 |
| Timing | +0xba | **+0xcc** | +0xcd | +0xce | 0x12 |
| Voicing | +0xcf | **+0xe1** | +0xe2 | +0xe3 | 0x12 |
| Range | +0x90 | **+0xa2** | +0xa3 | +0xa4 | 0x12 |
| Scale | +0x40 | **+0x52** | +0x53 | +0x54 | 0x12 |
| Channel | +0xe4 | **+0xf7** | +0xf8 | +0xf9 | 0x13 |
| Repeats | +0xfa | **+0x10c** | +0x10d | +0x10e | 0x12 |
| Accent | +0x10f | **+0x121** | +0x122 | +0x123 | 0x12 |
| Time (u16) | +0x124 | **+0x137** | +0x138 | +0x139 | 0x13 |
| Cycles | +0x14d | **+0x14e** | — | — (not lockable) | 0x01 |
| Length | +0x14b | **+0x14c** | — | — (not lockable) | 0x01 |

Notes / uncertainties:
- **Gap is +0x12 for 11 params**, +0x13 for the u16/late ones (Division, Time, Channel — value
  spans 2 bytes, so the record starts after it), +0x11 for Pitch. The robust rule: amount sits
  right after the param's 16-byte modulation run; for u16 values that run starts after both value
  bytes. The amount **offsets themselves are directly measured** (clean pair signatures), so the ±1
  gap variation is cosmetic.
- **Cycles & Length are NOT sequenced** — they live in the compact late cluster (`+0x14b…+0x14e`)
  with a random amount byte right after the value (gap 1) but **no 16-byte run** (so no phase) and
  **no lock byte** → matches the brief ("Cycles/Length not lockable").
- **Pitch lock `+0x68`*** collides with Pitch's own modulation run (default byte 168 there), and P4
  showed no change on the Pitch track, so Pitch lock could not be independently confirmed (could be
  encoded in-run, or simply not set in this take). Pitch *amount* `+0x66` is solid (P2 pair −20/+20).
- **P4 anomalies**: T3 (Cycles, "not lockable") shows `+0x29`=1 (the Pulses-lock offset) — spurious,
  unexplained; T7 (Pitch) shows no lock byte (see above); T8 (Length, not lockable) shows none.
  The other 13 tracks each set lock=1 at their own param's `amount+2`, so P4 actually locked the
  P2-set params on T1–8 and the P3-set params on T9–16 (the brief only listed T1–8).
- **Slew** offset is directly measured only for **Steps** (`+0x13`); for the other params it is
  inferred = `amount+1` (the byte between the confirmed amount and the confirmed lock). High
  structural confidence, but not individually swept.
- **Amount range** observed only at the extremes (−20 / +20) here; B23 saw a clean 0→12 ladder on
  the velocity slot, so full-scale ≈ ±20 (coarse). Stored as s8.
- **P7/P8 are DEFAULT** (no random programming) — verified: every amount/slew/lock/intensity offset
  reads 0 across both patterns (the lone non-zero, `+0x68`=168, is just a Pitch modulation-run byte).
  The owner's notes stopping at P6 is consistent.
- **Zone-A "unidentified runs" now resolved as modulation sequences**: the 8 named in the scoreboard
  (`+0x16,+0x68,+0x91,+0xbb,+0xd0,+0xfa,+0x110,+0x126`) are the modulation runs of Pulses(+0x15→run
  +0x16), Pitch(+0x55→+0x56‹adj +0x68 is mid-run›), Range(+0x90→+0x91), Timing(+0xba→+0xbb),
  Voicing(+0xcf→+0xd0), Repeats(+0xfa), Accent(+0x10f→+0x110), Time(+0x124→+0x126) — i.e. each
  sequenced param's 16-byte run, exactly as the amount map implies.
- None rebuild-proofed through the shipped parser yet (located only; consistent with B21–B23 status).

### 2026-06-26 — Banks 25–28 (Phrase/Groove length, Voicing direction, Repeat choke/tail)
Sources: `decode/samples/26_phrase_length` (8 blk), `decode/samples/28_groove_length` (8 blk),
`decode/samples/27_voicing_direction` (2 blk), `decode/samples/25_repeat_choke_tail` (2 blk).
Method: `t1_blockdiff.py --sweep` on the two monotonic banks (26/28); `t1_blockdiff.py F:0 F:1`
on the two 2-block banks (25/27). All four new fields fall into the **contiguous param table**
between the already-known `timing-sub +0x146 / phrase-shape +0x147 / groove-pattern +0x148` and
`track-length +0x14b` — the cluster is now fully packed `+0x144 … +0x14b` with no gaps, which is
strong structural corroboration for each byte being a real parameter.

| Param | Offset | Kind | Evidence | Confidence |
|---|---|---|---|---|
| **Phrase length** | `steps+0x144` | u8 enum | B26 blk0–6 (1,2,4,8,16,32,64 bars) = `6,5,4,3,2,1,0`; blk7 default=`4`. Map **`v → 2^(6−v)` bars** (0=64bar…4=4bar(default)…6=1bar). Only other diff = positional end-marker `+0x2b5`. Sits one before phrase-shape `+0x147` | high |
| **Groove length** | `steps+0x145` | u8 enum | B28 blk0–6 (1,2,4,8,16,32,64 bars) = `6,5,4,3,2,1,0`; blk7 default=`4`. Same map `v → 2^(6−v)` bars. Sits one before groove-pattern `+0x148`; in B26 this byte is constant `4` (its default), and `+0x144` is constant `4` in B28 — the two are cleanly distinct siblings | high |
| **Voicing note direction** | `steps+0x149` | u8 (0/1) | B27: the **only** byte differing between T1 and T2 (790 const, 1 vary). T1(Up)=`0`, T2(Down)=`1`. Constant `0` across all of B26/B28 (default Up) | medium-high (clean single-byte isolation, but only 2 samples — can't rule out a >2-value enum, e.g. Converge/Diverge modes) |
| **Repeat choke/tail mode** | `steps+0x14a` | u8 enum (0/1 seen) | B25: the **only** byte differing between the two blocks (790 const, 1 vary). blk0=`0`, blk1=`1`. Fills the last gap between voicing-direction `+0x149` and track-length `+0x14b`. Constant `0` across B26/B28 | **low–medium** — see caveat |

Caveats:
- **Repeat choke/tail (`+0x14a`)**: the owner's note says T1 has *Choke + Tail* set (two repeater
  sub-modes), yet only **one** byte differs and it carries values `0`/`1`. So either (a) it is a
  single enum for the repeater mode (e.g. `0`=Tail/normal, `1`=Choke, or vice-versa) and only one of
  the two described settings actually toggled this byte, or (b) choke and tail are packed as bitflags
  in this one byte (values seen are 0b0 / 0b1). With only 2 blocks we cannot disambiguate which mode
  is which, nor confirm two independent flags. **Offset = high confidence (clean isolation, fills the
  table gap); semantics = low confidence.** Repeats *amount* itself stays at `+0xfa` (=`1` in both).
- **Bar-length enum** is inverted/descending (`v → 2^(6−v)`): larger stored value = shorter phrase.
  Range observed 0–6; values >6 (if any longer settings exist) not sampled. Default for both = `4` (4 bars).
- None rebuild-proofed through the shipped parser (located only; consistent with B21–B24 status).
