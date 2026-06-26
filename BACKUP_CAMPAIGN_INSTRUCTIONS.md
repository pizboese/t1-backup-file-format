# T-1 decode backups — programming instructions (Backups 2–4)

Printable worksheet for hand-programming the remaining reverse-engineering backups on the
Torso T-1. Covers the campaign's **Backup 2 (Shape + Repeater)**, **Backup 3 (Groove + Tonal)**
and **Backup 4 (Modes + Routing + Global)** from
`/.claude/plans/i-want-you-to-zesty-owl.md`. Backup 1 (timing/feel) is already decoded
(`samples/20_backup1_params`), so it is **not** repeated here.

> **Ship all three in ONE backup.** Each "Backup" needs only ~6–9 of a bank's 16 patterns, so put
> them in three different **banks** of a single device backup:
> **Bank 0 = Shape+Repeater · Bank 1 = Groove+Tonal · Bank 2 = Modes+Routing+Global.**
> Program all three, then **manual-save → Backup → export the full zip** once. That single zip is
> everything.

---

## How these backups work (read first)

The decode method is a **monotonic sweep**: within each Pattern we change **exactly one
parameter** and step it up by one notch per track, leaving everything else identical. The target
byte then shows up in the file as a value that counts `1, 2, 3, …` across the 16 aligned track
blocks — which cuts straight through the per-track random noise. So the rules are:

1. **One parameter per Pattern.** The Pattern's title below names it.
2. **Identical base track on every track of that Pattern**, differing *only* in the target.
   Easiest workflow: program **Track 1**, then **copy the track** to Tracks 2…N, then change just
   the target parameter on each copy.
3. **Monotonic ladder:** Track 1 = lowest setting, then **+1 notch per track**. For a *bipolar*
   parameter "lowest" means the **full-negative** end (turn it all the way down on Track 1, then
   come up one notch per track through centre to the top). Equal steps; never skip around.
4. **No numeric display** on the device — values are read as 16 LEDs. Exactness doesn't matter;
   **strictly increasing, equal-sized steps** is all the diff needs. If a parameter has fewer
   distinct settings than 16 (e.g. 8 shapes), just use that many tracks and leave the rest empty.
5. Leave all non-target parameters at the **Base Track** defaults below so untouched bytes stay
   constant.

### Base Track (the identical starting point everywhere unless a table overrides it)

| Param | Setting |
|---|---|
| Steps | 16 |
| Pulses | 4 (Euclidean) — *except* where Pulses/Rotate/Repeats are the target |
| Pitch | C3 (single note) |
| Division | 1/16 |
| Cycles | 1 |
| Velocity | default (centre) |
| Sustain | default (centre) |
| Probability | default (off / centre) |
| Scale / Root | Chromatic / C |
| Style | default (poly, VB1) |
| MIDI channel | 1 |

> **Optional free cross-check (costs nothing):** give each bank a **distinct Tempo**
> (Bank 0 = 100, Bank 1 = 140, Bank 2 = 180 BPM). Tempo is already decoded as bank-summary
> bytes 0–1; three different values re-confirm it in the same backup.

---

# BANK 0 — Shape + Repeater

One Pattern per shape/repeater parameter. Base Track as above; only the named column changes
per track.

### P1 — Pulses (1 → 16)
Euclidean pulse count. (Gate is already decoded; this isolates the **pulse-count value byte**.)

| Track | Pulses |
|---|---|
| 1 | 1 |
| 2 | 2 |
| 3 | 3 |
| … | … (one more per track) |
| 16 | 16 |

### P2 — Rotate (0 → 15)
Base **Pulses = 8** (fixed) so rotation is meaningful; ladder Rotate only.

| Track | Rotate |
|---|---|
| 1 | 0 |
| 2 | 1 |
| 3 | 2 |
| … | … |
| 16 | 15 |

### P3 — Repeats (0 → 15)
Note-repeater count (full range is 0–48; 0–15 is a representative ladder).

| Track | Repeats |
|---|---|
| 1 | 0 |
| 2 | 1 |
| … | … |
| 16 | 15 |

### P4 — Ramp (lowest → highest)
Ramp shapes the repeat burst, so set **Repeats = 4** (fixed) on every track, then ladder Ramp one
notch per track from its lowest to highest setting.

| Track | Repeats (fixed) | Ramp |
|---|---|---|
| 1 | 4 | lowest |
| 2 | 4 | +1 notch |
| … | 4 | … |
| 16 | 4 | highest |

### P5 — Time / repeat spacing (note-value ladder)
Repeat spacing. **Repeats = 4** fixed; step Time through its note-value list, one value per track
(use as many tracks as there are values).

| Track | Repeats (fixed) | Time |
|---|---|---|
| 1 | 4 | shortest note value |
| 2 | 4 | next note value |
| … | 4 | … |
| N | 4 | longest note value |

### P6 — Pace (full-negative → full-positive)
Bipolar repeat-timing skew. **Repeats = 4** fixed.

| Track | Repeats (fixed) | Pace |
|---|---|---|
| 1 | 4 | full negative |
| 2 | 4 | +1 notch |
| … | 4 | … through centre … |
| 16 | 4 | full positive |

### P7 — Range / pitch-variation amount (lowest → highest)

| Track | Range |
|---|---|
| 1 | lowest (0) |
| 2 | +1 notch |
| … | … |
| 16 | highest |

### P8 — Phrase: shape (Tracks 1–8) + length (Tracks 9–16)
Two sweeps in one pattern. Tracks 1–8 step through the **8 Phrase shapes**; Tracks 9–16 fix the
shape (shape 1) and ladder **Phrase length** 1→8 bars.

| Track | Phrase shape | Phrase length |
|---|---|---|
| 1 | shape 1 | default |
| 2 | shape 2 | default |
| 3 | shape 3 | default |
| 4 | shape 4 | default |
| 5 | shape 5 | default |
| 6 | shape 6 | default |
| 7 | shape 7 | default |
| 8 | shape 8 | default |
| 9 | shape 1 | 1 bar |
| 10 | shape 1 | 2 bar |
| 11 | shape 1 | 3 bar |
| 12 | shape 1 | 4 bar |
| 13 | shape 1 | 5 bar |
| 14 | shape 1 | 6 bar |
| 15 | shape 1 | 7 bar |
| 16 | shape 1 | 8 bar |

### P9 — Voicing / motion amount (lowest → highest)
Keep **Style fixed at default (poly, VB1)** — Style is already decoded; this isolates the separate
*motion-amount* byte.

| Track | Style (fixed) | Voicing amount |
|---|---|---|
| 1 | poly VB1 | lowest |
| 2 | poly VB1 | +1 notch |
| … | poly VB1 | … |
| 16 | poly VB1 | highest |

---

# BANK 1 — Groove + Tonal

### P1 — Accent / amount (full-negative → full-positive)
Bipolar. To make it expose its byte clearly, give the base a **3-note chord** (C3-E3-G3) so accent
has notes to act on, identical on every track.

| Track | Accent |
|---|---|
| 1 | full negative |
| 2 | +1 notch |
| … | … through centre … |
| 16 | full positive |

### P2 — Groove: pattern (Tracks 1–8) + length (Tracks 9–16)
Tracks 1–8 step the **8 Groove patterns**; Tracks 9–16 fix pattern 1 and ladder **Groove length**
1→8 bars.

| Track | Groove pattern | Groove length |
|---|---|---|
| 1 | pattern 1 | default |
| 2 | pattern 2 | default |
| 3 | pattern 3 | default |
| 4 | pattern 4 | default |
| 5 | pattern 5 | default |
| 6 | pattern 6 | default |
| 7 | pattern 7 | default |
| 8 | pattern 8 | default |
| 9 | pattern 1 | 1 bar |
| 10 | pattern 1 | 2 bar |
| 11 | pattern 1 | 3 bar |
| 12 | pattern 1 | 4 bar |
| 13 | pattern 1 | 5 bar |
| 14 | pattern 1 | 6 bar |
| 15 | pattern 1 | 7 bar |
| 16 | pattern 1 | 8 bar |

### P3 — Harmony (monotonic, one direction)
Harmony is hysteretic, so **program in ONE direction only** (never back off). Track 1 = no
harmony, then +1 notch per track upward.

| Track | Harmony |
|---|---|
| 1 | 0 (none) |
| 2 | +1 notch |
| 3 | +2 |
| … | … |
| 16 | +15 |

### P4 — Scale (every preset, in panel order)
One scale preset per track, stepping through the **full front-panel scale list** (VB1, VB2, …).
Use as many tracks as there are presets. This confirms the indices past the known 0–6.

| Track | Scale |
|---|---|
| 1 | scale 1 (Chromatic) |
| 2 | scale 2 |
| 3 | scale 3 |
| … | … (one preset per track, panel order) |
| N | last preset |

### P5 — User scale (VB16)
On **Track 1**, build a **custom user scale** (VB16) with a deliberate, easy-to-recognise note set
— e.g. enable scale degrees **C, D#, F#, A** only. Leave Tracks 2–3 as two *different* custom sets
(e.g. C-E-G; C-D-E-F-G-A-B) so the diff shows how the note-set is stored.

| Track | User scale notes |
|---|---|
| 1 | C, D#, F#, A |
| 2 | C, E, G |
| 3 | C, D, E, F, G, A, B |

### P6 — Per-step Accent locks (find the lock id)
Not a track ladder — **one track** with per-step Accent edits at known steps/values, to expose the
per-step Accent lock record + id. Base = full 16-step gate, single note C3.

| Track | Per-step Accent locks |
|---|---|
| 1 | step 5 → min accent · step 9 → centre · step 13 → max accent (leave all other steps default) |

### P7 — Per-step Range locks (find the lock id)
Same idea for Range. One track, edits on known steps.

| Track | Per-step Range locks |
|---|---|
| 1 | step 5 → min · step 9 → mid · step 13 → max (other steps default) |

---

# BANK 2 — Modes + Routing + Global

### P1 — Track Mode: Note / CC / FX (repeating ladder)
Cycle the three track modes across tracks so the mode flag reads `0,1,2,0,1,2,…`.

| Track | Mode |
|---|---|
| 1 | Note |
| 2 | CC |
| 3 | FX |
| 4 | Note |
| 5 | CC |
| 6 | FX |
| 7 | Note |
| 8 | CC |
| 9 | FX |
| 10 | Note |
| 11 | CC |
| 12 | FX |
| 13 | Note |
| 14 | CC |
| 15 | FX |
| 16 | Note |

### P2 — CC tracks: distinct CC number + value
All tracks in **CC mode**; give each a different **CC number** and a different **CC value**, both
laddered, so the diff exposes both fields at once.

| Track | Mode | CC number | CC value |
|---|---|---|---|
| 1 | CC | 1 | 0 |
| 2 | CC | 2 | 8 |
| 3 | CC | 3 | 16 |
| 4 | CC | 4 | 24 |
| 5 | CC | 5 | 32 |
| 6 | CC | 6 | 40 |
| 7 | CC | 7 | 48 |
| 8 | CC | 8 | 56 |
| 9 | CC | 9 | 64 |
| 10 | CC | 10 | 72 |
| 11 | CC | 11 | 80 |
| 12 | CC | 12 | 88 |
| 13 | CC | 13 | 96 |
| 14 | CC | 14 | 104 |
| 15 | CC | 15 | 112 |
| 16 | CC | 16 | 120 |

### P3 — Per-step CC locks (find CC lock id)
One CC-mode track with per-step CC-value edits at known steps.

| Track | Mode | Per-step CC-value locks |
|---|---|---|
| 1 | CC (CC# 1) | step 5 → 16 · step 9 → 64 · step 13 → 112 (other steps default) |

### P4 — FX track config
A couple of **FX-mode** tracks with different FX configuration (e.g. pass-through vs an N-pulse
setting) to locate the FX config fields.

| Track | Mode | FX config |
|---|---|---|
| 1 | FX | pass-through / default |
| 2 | FX | variant A (e.g. fewer pulses) |
| 3 | FX | variant B (different target/amount) |

### P5 — Output / internal routing toggles
All Note-mode, **MIDI channel fixed at 1** (so the channel mask stays constant), but toggle the
**internal/output routing** option in a ladder so only the routing field moves.

| Track | Channel (fixed) | Output routing |
|---|---|---|
| 1 | 1 | routing setting 1 |
| 2 | 1 | routing setting 2 |
| 3 | 1 | routing setting 3 |
| … | 1 | … (one per track) |
| N | 1 | last setting |

### P6 — Mute / enable
Identical tracks; **mute the first 8, leave 9–16 unmuted** so the mute flag shows a clean
`1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0` split.

| Track | Muted? |
|---|---|
| 1–8 | muted |
| 9–16 | unmuted |

### P7 — Random amount (0 → 15) on one parameter
All tracks identical except the **Random amount applied to Velocity**, laddered. This finds the
per-param random **amount** byte (distinct from the random buffer itself).

| Track | Random amount (on Velocity) |
|---|---|
| 1 | 0 |
| 2 | 1 |
| … | … |
| 16 | 15 |

### P8 — Random Rate (lowest → highest)
Same base; ladder the **Random Rate** (advance speed) one notch per track.

| Track | Random Rate |
|---|---|
| 1 | lowest |
| 2 | +1 notch |
| … | … |
| 16 | highest |

---

## After programming — what to send

1. **Manual-save** each pattern you edited, on each bank.
2. **Backup → export** the full backup zip (all 8 banks).
3. Send that single zip. It contains all three banks (Shape+Repeater, Groove+Tonal,
   Modes+Routing+Global) — everything needed to decode the remaining parameters in one pass.

### What we'll do with it (for reference)
For each bank we align the track blocks and run `t1_blockdiff.py --sweep`; the laddered byte that
counts `1,2,3,…` is the field. Each decoded field is then added as a `samples/NN_*` reference,
folded into `t1_format.py` / `midi_to_t1.py` / `t1_to_midi.py`, and proven by
`test_roundtrip.py` (byte-for-byte). Order of attack matches the banks above.
