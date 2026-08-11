# T-1 Feature Inventory + Backup-Acquisition Campaign

## Context
Goal: account for **every bit** of the `.t1` block. We have a byte-exact roundtrip and a
hardware-verified importer, but a large part of the per-track "steps-region" is still an
opaque random buffer + undecoded parameter value-bytes. The T-1 manual defines a *closed,
enumerable* set of per-track parameters; the **Random Behavior Reference** in particular gives a
closed list of the 16 modulation-sequenced params, and Zone A of the block holds exactly one
17-byte run per sequenced param — so the remaining decode is bounded, not open-ended.

This plan is the **map**: (1) a complete feature list with manual URLs and current decode status,
(2) an ordered, max-density backup campaign to decode the rest, structured for the user's
"one backup per request, pack variations, monotonic sweeps" methodology.

User decisions (this session):
- **Order:** MIDI-import-critical first (Timing, Delay, Tempo, track Length, free Division, …),
  then **Shape+Repeater**, then **Groove+Tonal**, then **Modes+Routing+Global**.
- **Packing:** max density — one parameter per pattern, swept monotonically across up to 16
  tracks ⇒ ~16 params per backup, fewest device round-trips.

---

## Part 1 — Complete feature inventory (manual → format status)

Status legend: ✅ DECODED (byte located + synthesized) · 🟡 PARTIAL (located, gaps remain) ·
❌ UNDECODED. Byte offsets are relative to the `steps` field unless noted.

**Hardware-validation tag** (added 2026-06-27, rounds 1–3 of `decode/verify/verify_findings_*.zip`):
`[hw✓]` = device confirmed our authored value · `[hw?]` = test in the backup but the user could
not isolate it on device (default-collision or no readout) · `[hw–]` = located but not exercised
in any verify round yet. See "Hardware verification scoreboard" below for the full mapping.

### Data model — https://docs.torsoelectronics.com/t1/what-is-the-t1/t1-overview/data-structure
Project → 16 Banks → 16 Patterns → 16 Tracks → up to 16 Cycles → up to 64 Steps. Bank holds a
shared Tempo. ✅ container/hierarchy decoded (FORMAT.md).

### Shape — https://docs.torsoelectronics.com/t1/parameter-reference/shape/
| Feature | URL (page) | Range | Status / location |
|---|---|---|---|
| Steps (track length) | `/shape/steps` | 1–64, def 16 | ✅ `steps+0x00`; gate = 64 B @ `run+0x0c` [hw✓ B0 T1] |
| Pulses (Euclidean count) | `/shape/pulses-rotate` | 1–steps | ✅ value at `steps+0x15` (located by B0 T2 verify; written 8, device read 8) [hw✓ B0 T2] |
| Rotate | `/shape/pulses-rotate` | directional | ✅ `steps+0x13a` u8 (FORMAT_DECODE B21) [hw? B0 T3 — user could not verify reading on device] |
| Cycles (count) | `/shape/cycles` | 1–16, def 4 | ✅ `steps+0x14d`; full per-cycle engine decoded [hw✓ B0 T14] |
| Division | `/shape/division` | note values; Free mode | ✅ `steps+0x2a` u16 + free-flag `steps+0x299` (B1) [hw✓ B0 T15 fixed div + T16 free] |
| Repeats | `/shape/repeats-ramp` | 0–48 (+∞) | ✅ `steps+0xfa` u8 (FORMAT_DECODE B21) [hw✓ B0 T4] |
| Ramp | `/shape/repeats-ramp` | directional | ✅ `steps+0x13b` s8 bipolar (FORMAT_DECODE B21) [hw✓ B0 T5] |
| Time (repeat spacing) | `/shape/time-pace` | note values | ✅ `steps+0x124` u16 [hw? B0 T6 — wrote `24` (= 1/16), but that IS the default; not distinguishable on device, so the byte placement is unproven by this round] |
| Pace | `/shape/time-pace` | bipolar | ✅ `steps+0x13c` s8 (FORMAT_DECODE B21) [hw✓ B0 T7] |
| Voicing (motion amount) | `/shape/voicing-style` | continuous | ✅ amount `steps+0xcf` s8 [hw✓ B0 T11]; direction `steps+0x149` u8 [hw✓ B0 T12]; Style ✅ |
| Style | `/shape/voicing-style` | poly 0–4 / mono 8–12 | ✅ `steps+0x13d` [hw✓ B0 T13 = mono/arp index 8] |
| Range | `/shape/range-phrase` | pitch-variation amt | ✅ `steps+0x90` s8 bipolar (FORMAT_DECODE B21) [hw✓ B0 T8] |
| Phrase (shape + length) | `/shape/range-phrase` | 8 shapes; 1–64 bars | ✅ shape `steps+0x147` enum [hw✓ B0 T9 = 4th]; length `steps+0x144` enum `v→2^(6−v)` bars [hw✓ B0 T10 = 8 bars] |

### Groove — https://docs.torsoelectronics.com/t1/parameter-reference/groove/
| Feature | URL | Range | Status |
|---|---|---|---|
| Velocity (track + per-step) | `/groove/velocity-probability` | 0–127, 1:1 MIDI | ✅ `steps+0x7b`; lock id `0x0a` [hw✓ B1 T1 track + per-step locks at step5/step9] |
| Probability | `/groove/velocity-probability` | bipolar, center 0 | ✅ `steps+0x79` s8 (B1) [hw✓ B1 T2] |
| Sustain (track + per-step) | `/groove/sustain` | 0–127, def 64=1 div | ✅ `steps+0xa5`; lock id `0x0e`; log law [hw✓ B1 T3 track + per-step lock at step5] |
| Timing (swing) | `/groove/timing-delay` | bipolar, x1/x2/x4 | ✅ amount `steps+0xba` s8; sub `+0x146` enum {3=/4, 4=/1 default, 5=/2} (B1) [hw✓ B1 T4 amount + sub=/2; **round-2 wrote sub=1 → device rejected the whole bank**, fixed in round 3 — enum validation matters] |
| Delay (track shift) | `/groove/timing-delay` | bipolar | ✅ `steps+0x13e` s8 (B1) [hw✓ B1 T5] |
| Accent (amount) | `/groove/accent-groove` | bipolar | ✅ track `steps+0x10f` s8 ±20 (FORMAT_DECODE B22+B29) [hw✓ B1 T6]; per-step lock id `0x18` [hw–] |
| Groove (pattern + length) | `/groove/accent-groove` | 8 patterns; 1–64 bars | ✅ pattern `steps+0x148` enum (B22) [hw✓ B1 T7 = 4th]; length `steps+0x145` enum `v→2^(6−v)` bars (B28) [hw✓ B1 T8 = 8 bars] |

### Tonal — https://docs.torsoelectronics.com/t1/parameter-reference/tonal/
| Feature | URL | Range | Status |
|---|---|---|---|
| Pitch (track + per-step + per-cycle) | `/tonal/pitch-harmony` | absolute, C3=60 | ✅ header list + locks + cycle overrides (already shipped-proven & hw-verified pre-campaign); chord-default B2 T5 [hw✓ round 1, shifted slot — chord played on the device] |
| Harmony | `/tonal/pitch-harmony` | hysteretic shift | 🟡 located at `run−0x10` (FORMAT_DECODE); B2 T3 [hw✓ round 1, shifted slot — value showed up on device] but the CHECK caveat applies: storing fixed pitches does not exercise the algorithmic shift engine, so this only confirms the BYTE, not the FEATURE. Algorithmic probe still TODO. |
| Scale | `/tonal/scale-root` | presets + user (VB16) | ✅ preset `steps+0x40` 0–7 + custom scale-degree table in the block header (FORMAT_DECODE B22, decode-rebuild byte-for-byte) [hw✓ B2 T1 preset=Major (round 2); hw✓ B2 T4 custom degrees (round 1, shifted slot)] |
| Root | `/tonal/scale-root` | C–B (0–11) | ✅ `steps+0x13f` [hw✓ B2 T2 = G] |

### Setup — https://docs.torsoelectronics.com/t1/parameter-reference/setup/
| Feature | URL | Range | Status |
|---|---|---|---|
| Length (track loop, bars) | `/setup/length-quantize` | 1/64 bar–16 bar, ∞, def 1 | ✅ `steps+0x14b` enum 0–15 (B1) [hw✓ B4 T1 = 2 bars] |
| Quantize (per-pattern) | `/setup/length-quantize` | bar divisions | ✅ pattern-trailer 4th byte, Length enum (B1) [hw✓ B4 bank-level enum=3] |
| Channel | `/setup/channel-output` | MIDI 1–16 | ✅ via out-mask `steps+0xe4` (shipped-proven pre-campaign); MIDI channel B3 T5 = 5 [hw✓ round 1, shifted slot] |
| Output (internal routing) | `/setup/channel-output` | per-track toggles | ✅ `steps+0x297` u16 (FORMAT_DECODE B23) [hw✓ B3 T3 routed to track 3, round 1 shifted slot] |
| Tempo | `/setup/tempo` | 24–280, def 120, **per-bank** | ✅ bank summary bytes 0–1, u16 LE BPM (B1) [hw✓ B4 bank-level = 132 BPM] |
| Random (amount per param) | `/setup/random-rate` | per-param variance | ✅ amount `value+0x12` s8, lock `value+0x14`, slew `value+0x13`, phase=rotation of 16-B mod seq (FORMAT_DECODE B24); B4 T4 Velocity amount+lock [hw✓ round 1, shifted slot]; per-param coverage for OTHER params + slew/phase (live modulation) still not exercised |
| Rate | `/setup/random-rate` | advance speed | ✅ `steps+0x141` u16 (FORMAT_DECODE B24) [hw✓ B4 T2 = 1/8] |

### Tracks / Modes — https://docs.torsoelectronics.com/t1/tracks-patterns-banks/tracks/
| Feature | URL | Status |
|---|---|---|
| Track Mode Note/CC/FX | `/tracks/modes/cc_mode`, `/tracks/modes/fx_mode` | ✅ mode at `steps+0x154` (0=Note, 1=CC, 2=FX); CC#: `steps+0x16a + 0x17·N`, CC value: `steps+0x155`, enable: `steps+0x16b` (FORMAT_DECODE B23+B29) [hw✓ B3 T1 CC mode + CC#74 + value~64; hw✓ B3 T2 FX mode; hw✓ B3 T6 Note default — round 1, shifted slot] |
| Setting parameters (grid) | `/tracks/setting-parameters` | reference only |
| Mute / enable | `/miscellaneous/mute` | ✅ `run−0x0d` u8 (1=muted) (FORMAT_DECODE) — header-adjacent, not steps-relative [hw✓ B3 T4 muted on device, round 1 shifted slot] |

### Core concepts (cross-cutting, mostly mechanics of the above)
- Euclidean rhythms `/core-concepts/euclidean-rhythms` · Custom rhythms `/core-concepts/custom-rhythms`
  → resolved into the ✅ 64-B gate.
- Note Repeater `/core-concepts/note-repeater/` (+ `/making-repeats`, `/midi-looping`) → Repeats/Time/Pace/Ramp ❌.
- Pitch & Chords `/core-concepts/pitch-chords/` (+ `/chords-arpeggios`, `/generating-melodies`, `/pitch-menu`)
  → chords ✅; melody-generation = Range/Phrase ❌.
- Modulation `/core-concepts/modulation/` (+ `/random-modulation`, `/phrase-groove`) → Random buffers (Zone A) ❌ runs.
- Per-step editing `/core-concepts/per-step-editing` → pitch/velocity/sustain locks ✅; **other per-step locks ❌** (Timing, Repeats, CC, tonal).
- Cycles `/core-concepts/cycles` → ✅ fully decoded.

### Random Behavior Reference (KEY — bounds the Zone-A decode)
https://docs.torsoelectronics.com/t1/appendix/random-behavior — the **16 sequenced params**, each
owning one 17-byte Zone-A run. As of 2026-06-26 **all 16 runs are located** (FORMAT_DECODE
"Banks 21–28"): per-cycle Steps`+0x00`, Pulses`+0x15`, Cycles`+0x14d`, Repeats`+0xfa`,
Velocity`+0x7b`, Pitch`+0x55`, Scale`+0x40`, Length`+0x14b`; random-rate Division`+0x2a`,
Time`+0x124`, Voicing`+0xcf`, Range`+0x90`, Sustain`+0xa5`, Accent`+0x10f`, Timing`+0xba`,
Channel/mask`+0xe4`. The 8 formerly-❌ runs (`+0x15,+0x90,+0xcf,+0xfa,+0x10f,+0x124,+0x13a,…`)
matched to their named params; the original "unidentified" list is resolved. Per-param shared
record layout `value | 16-B mod seq | tail | amount(+0x12,s8) | slew(+0x13) | lock(+0x14)`.

### Config / appendix (device settings, mostly outside the per-bank block)
`/appendix/t1-config/*` (home, project, midi-io, midi-fx, cv-gate, sync, wi-fi, misc),
`/appendix/quick-commands`, `/appendix/midi-program-change-map`, `/midi-and-analog-sync/*`,
`/miscellaneous/*` (mute, temporary-control, chromatic-keyboard, hold, clear-copy). Mostly live in
`Settings.json`/`Wifi.json`, not the `.t1` bank — **lower priority** for format decode; revisit only
if a feature proves to be bank-stored.

---

## Part 1.5 — Hardware verification scoreboard (rounds 1–3, 2026-06-27)

Source: `decode/verify/CHECK{1,2,3}.md` (on-device check sheets) + `decode/verify/verify_findings_3.zip`
(the round-3 write-direction probe). `make_verify_backup.py` synthesizes one bank per device page
(0=SHAPE, 1=GROOVE, 2=TONAL, 3=MODES/ROUTING, 4=GLOBAL/RANDOM) and writes each PLAN row to a
chosen value; the user restores it and ticks per row.

### Rounds (decoded by the verification process itself)
- **Round 1** (`verify_findings.zip` → CHECK1.md): synth bug — `end_mark = i+2` left slot 2 empty,
  shifted later tracks +1. Bank 0 (16 tracks → T16 at out-of-range slot 17) **rejected**; banks
  2/3/4 loaded with the visible shift; bank 1 also rejected (then-misdiagnosed).
- **Round 2** (`verify_findings_2.zip` → CHECK2.md): end-marker fix; **banks 0/2/3/4 loaded** with
  tracks on the named slots. Bank 1 still rejected.
- **Round 3** (`verify_findings_3.zip` → CHECK3.md): root cause for bank 1 was `timing_sub=1`
  on B1 T4 — `steps+0x146` is a 3-point enum **{3=/4, 4=/1 (default), 5=/2}** and `1` is invalid.
  Fixed to `5`; **all 5 banks now load**. ← **device-decoded rule: out-of-range enum values reject
  the entire bank load, not just the field.**

### Per-bank results (rounds 1–3 combined; CHECK1 "OK but on T*" notes COUNT as hw✓ because the
parameter value did show up correctly on device — only the slot was wrong due to the round-1
builder bug, which has since been fixed)
- **Bank 0 — SHAPE (16 tests, round 2).** 14 hw✓ (Steps, Pulses, Repeats, Ramp, Pace, Range,
  Phrase shape, Phrase length, Voicing amount, Voicing direction, Style, Cycles, Division,
  Division FREE), 2 hw? (Rotate "not verifiable" on device; Time wrote 24 = default `1/16` so
  the byte placement is unproven by this test). Bank 0 couldn't be tested in round 1 (didn't load).
- **Bank 1 — GROOVE (9 tests, round 3).** All 9 hw✓ (Velocity track + step locks, Probability,
  Sustain track + step lock, Timing amount + sub, Delay, Accent track, Groove pattern, Groove
  length, Repeat Choke/Tail). Bank 1 couldn't be tested in rounds 1–2 (didn't load).
- **Bank 2 — TONAL (5 tests).** All 5 hw✓ (T1 Scale=Major round 2; T2 Root=G round 2;
  T3 Harmony, T4 Custom scale, T5 Chord default — all round 1 at shifted slot, value appeared).
  Caveat on Harmony: fixed-pitch test confirms the BYTE writes but does not exercise the
  algorithmic shift engine.
- **Bank 3 — MODES/ROUTING (6 tests).** All 6 hw✓ (T1 CC mode + encoder, T2 FX mode — round 2;
  T3 Internal routing, T4 Mute, T5 MIDI channel = 5, T6 Note mode default — round 1 shifted slot).
- **Bank 4 — GLOBAL/RANDOM (6 tests + bank-level).** All 6 hw✓ + bank-level Tempo=132 BPM hw✓,
  Quantize enum=3 hw✓ (T1 Track Length=2bar round 2; T2 Rate=1/8 round 2; T3 Random intensity,
  T4 Random amount+lock for Velocity, T5 Retrigger — round 1 shifted slot; T6 Track selection
  cursor round 1).

### Flips from ❌ → ✅(located) → ✅ hw✓ this campaign
Pulses, Rotate(located only), Repeats, Ramp, Time(located only), Pace, Range, Phrase shape,
Phrase length, Voicing amount + direction, Accent track amount, Groove pattern + length,
Internal-routing offset, Track Mode (Note/CC/FX) + CC#/value/enable, Mute flag, Random Rate,
Random amount/slew/lock + phase mechanics, custom-scale-degree table, Tempo/Quantize/Length
placements, Repeater choke/tail, Retrigger gate bit, Track selection cursor.

### Still missing — concrete TODO

**(a) Tests in the backup that need a redesign before they can pass.**
- **Bank 0 T6 Time** — wrote `1/16` which IS the default → cannot distinguish at the device.
  Re-author to a non-default value (e.g. `1/8` = 48) next round.
- **Bank 0 T3 Rotate** — user reported "not verifiable" on device; need a different read-out
  strategy (programmed Pulses with visible Rotate offset on the gate).
- **Bank 2 T3 Harmony** — fixed-pitch test does not exercise the Harmony shift engine. Needs an
  algorithmic probe (set track Pitch + Harmony=N, observe transposed playback) — outside the
  static-byte verify pattern.

**(b) Findings the verify backup does NOT exercise at all** (carried over from
`CHECK*.md "Findings NOT directly exercised here"`):
- Random **slew** (`value+0x13`) and **phase** (16-B sequence rotation) — observable only via live
  modulation, not a static byte read.
- Random **amount/lock** for params **other than Velocity** (only one slot per param is set).
- Per-step **locks** beyond velocity/sustain: Accent (id `0x18`), Range (`0x0c`), Timing, CC
  (`0x80`) — `midi_to_t1.build_track_block` only emits velocity/sustain groove locks + pitch
  locks; the verify builder inherits that limit.
- **Multi-track selection set** (extended per-pattern trailer the shipped builder under-emits) —
  only the single saved cursor is authored.
- Per-cycle **track-param** overrides and **cycle-pitch** overrides (cycle COUNT alone is
  exercised in B0 T14).
- Per-step **pitch chord locks** (shipped + hw-verified pre-campaign — a plain chord default
  appears at B2 T5 instead).

### Summary
**Decoded coverage: 100% of PLAN.md's enumerable rows are located.** Every formerly-❌ row except
Harmony (now 🟡 — byte located + hw-confirmed, but the algorithmic engine itself not exercised)
flipped to ✅. **Hardware validation: ~95%** — 40 of 42 testable per-track values are hw✓ (plus
bank-level Tempo + Quantize), with 2 caveat rows (B0 T3 Rotate "not verifiable", B0 T6 Time
default-collision) and 1 semantic-only caveat (B2 T3 Harmony byte-only). What remains is the
class-(b) list above: live-modulation effects (Random slew/phase), per-param Random amount/lock
beyond Velocity, the four per-step lock IDs the builder doesn't emit, the multi-track selection
set, and per-cycle param/pitch overrides — all outside what a static-byte verify backup can cover.

---

## Part 2 — Backup-acquisition campaign (ordered, max-density)

**Structure of every backup:** one undecoded parameter per Pattern; within that pattern, program
the **same base track** across N tracks with the parameter set to a **monotonic ladder**
(value index 1,2,3,… per track). Diff aligned blocks (`t1_blockdiff.py --sweep`) → the field shows
up as a byte counting 1,2,3,…, cutting through per-track random noise. ~16 params per backup.
Keep all other params at defaults so non-target bytes stay constant (determinism).

Tooling already in repo: `t1_blockdiff.py` (sweep + random-reroll), `t1_annotate.py`
(show/diff/sweep), `t1_cycles.py`, `test_roundtrip.py`. Add a sample folder per backup under
`samples/NN_<name>/` with notes (programmed values + LED readings) like existing folders.

### Backup 1 — "import-critical timing/feel" (FIRST)
Pack these one-per-pattern, monotonic across tracks:
- **Timing (swing)** — ladder of swing amounts; repeat at subdivision x1/x2/x4 (extra patterns).
- **Delay** — bipolar ladder (track-shift), negative + positive.
- **Track Length** — 1/64 → 16 bar ladder (the loop-length field, **distinct from Steps**).
- **Quantize** — per-pattern ladder (note: per-pattern scope, so vary across *patterns*, read once/pattern).
- **Free Division mode** — fixed vs free at several continuous values (compare to known `steps+0x2a`).
- **Probability** — 0→100% ladder (often import-relevant for note thinning).
- Per-step **Timing/Sustain locks** already ✅; add a per-step **Timing lock** track to find that lock id.
- **Tempo is per-bank → cannot sweep within one bank.** Handle by a *second* deliverable in the
  same request: set a **different Tempo per bank (0.t1…7.t1)** in one full backup, diff banks →
  isolates the tempo field + confirms it lives in the bank summary/header, not the block.

### Backup 2 — Shape + Repeater
Pulses (1–16 ladder, watch the value-byte vs the resolved gate), Rotate (directional ladder),
Repeats (0,1,2,…,48 representative ladder), Ramp, Time (note-value ladder), Pace (bipolar),
Range (amount ladder), Phrase (8 shapes + a length ladder), Voicing amount (with Style fixed).
Each identifies one of the 8 unlocated Zone-A runs **and** its value-byte. Use the
random-reroll variant (re-roll one param's random per pattern copy) where the value-byte is
ambiguous, to pin the 17-byte run offset.

### Backup 3 — Groove + Tonal
Accent amount (bipolar ladder), Groove pattern (8 options) + Groove length ladder, Harmony
(stepwise shifts — note hysteresis: program monotonically in one direction), full **Scale** table
(every preset front-panel scale → confirm indices past 0–6) + a **user scale** (VB16) to find how
custom note-sets are stored, Length/Quantize cross-checks. Plus per-step **Accent/Range** locks
to extend the lock-id table.

### Backup 4 — Modes + Routing + Global
Track **Mode** Note/CC/FX (ladder Note,CC,FX across tracks → mode flag); **CC tracks** with
distinct CC# + value (find CC-number + CC-value fields, and per-step CC locks); **FX track**
config (pass-through vs N-pulse); **Output** internal track-routing toggles (vs the already-known
channel mask); **Mute/enable** (mute some tracks → find the flag); **Random amount + Rate**
(set Random amount nonzero on one param across a ladder → find the amount-byte distinct from the
buffer).

### Notes on efficiency / correctness
- Always start each swept track from an **identical base** (same pitch, gate, defaults) so the
  only moving byte is the target — exploits the device's determinism.
- Prefer **index-style ladders** (1,2,3,…) over arbitrary values: a monotonically counting byte is
  unmistakable in the diff even amid random state.
- Where a param is *both* track-level and per-step lockable, capture both in the same backup
  (one pattern track-level ladder, one pattern with per-step locks) to get the field **and** its
  lock-id together.
- Reuse the existing `samples/` discipline: extract `.t1`, write a `README`-style note with
  programmed values + LED readings.

---

## Part 3 — Verification (per decoded field)
For each newly decoded field:
1. Add the new sample bank under `samples/NN_*`; run `python3 test_roundtrip.py` → must stay
   **ALL PASS** (byte-for-byte rebuild proves we model the field, not just locate it).
2. Update the parser (`t1_format.py` / `t1_cycles.py`) to read the field; confirm it reports the
   programmed ladder (1,2,3,…).
3. For import-relevant fields, extend `midi_to_t1.py` to *emit* the field and the exporter
   (`t1_to_midi.py`) to read it; re-run `test_roundtrip.py`.
4. Document the offset + semantics in `FORMAT.md` (status table + a decode note), and update
   CLAUDE.md status bullets.
5. For load-affecting fields (mode/markers/length), build a `--new-backup` single-bank zip and
   confirm on hardware (non-destructive single-bank restore).

## Deliverable of this task
The feature inventory above **is** the running checklist. As each row flips to ✅ we cross it off,
working in the agreed order (timing/import-critical → Shape+Repeater → Groove+Tonal →
Modes+Routing+Global), one backup at a time, "no bit left without our understanding."
