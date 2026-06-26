# T-1 decode backup — programming instructions (Open items)

Printable worksheet for hand-programming the **still-open** reverse-engineering items on the
Torso T-1 — the handful of parameters that the earlier campaign (`samples/20`–`samples/28`,
Backups 1–6) only *partly* exercised, plus one feature not yet touched at all. Everything here
fits in a **single bank**, so it ships as **one backup**.

> **Ship it all in ONE backup.** Program the patterns below into **Bank 0**, then
> **manual-save → Backup → export the full zip** once. That single zip is everything we need.

The four open items (from `decode/FORMAT_DECODE.md` and the `decode/CLAUDE.md` TODO):

1. **Custom encoder CC#** — only the *default* mapping (CC# = 70 + encoder index, i.e. 70/71) was
   ever exercised (B23). The literal custom-CC-number byte was never written, so its offset is
   unknown. We need a pattern that **reassigns an encoder's CC number** across tracks.
2. **Bipolar positive half** for **Ramp / Pace / Range / Voicing / Accent** — B21/B22 only swept the
   negative half (`−20…−6`) and then jumped straight to the extreme `+20` on the last track. The
   **mid-positive range and its granularity are unconfirmed**. We need a clean centre → full-positive
   sweep of each.
3. **Repeat choke vs tail** — one byte at `steps+0x14a` (B25) carries the repeater end-behaviour, but
   the two modes (choke, tail) were programmed *together* on one track, so only a single value (`1`)
   was seen. We need a pattern that **isolates choke vs tail** (and "neither" / "both").
4. **Retrigger steps** — a per-track feature **not exercised at all yet**. We need a monotonic ladder
   to expose its byte.

---

## How these backups work (read first)

The decode method is a **monotonic sweep**: within each Pattern we change **exactly one parameter**
and step it up by one notch per track, leaving everything else identical. The target byte then shows
up in the file as a value that counts `1, 2, 3, …` across the 16 aligned track blocks — which cuts
straight through the per-track random noise. So the rules are:

1. **One parameter per Pattern.** The Pattern's title below names it.
2. **Identical base track on every track of that Pattern**, differing *only* in the target.
   Easiest workflow: program **Track 1**, then **copy the track** to Tracks 2…N, then change just
   the target parameter on each copy.
3. **Monotonic ladder:** Track 1 = lowest setting, then **+1 notch per track**. For a *bipolar*
   parameter "lowest" usually means the full-negative end — **but here the bipolar patterns
   deliberately start at CENTRE and climb to full-positive** (that is the half we still need; see each
   table). Equal steps; never skip around.
4. **No numeric display** on the device — values are read as 16 LEDs. Exactness doesn't matter;
   **strictly increasing, equal-sized steps** is all the diff needs. If a parameter has fewer
   distinct settings than 16, just use that many tracks and leave the rest empty.
5. Leave all non-target parameters at the **Base Track** defaults below so untouched bytes stay
   constant.

### Base Track (the identical starting point everywhere unless a table overrides it)

| Param        | Setting                                                                    |
| ------------ | -------------------------------------------------------------------------- |
| Steps        | 16                                                                         |
| Pulses       | 4 (Euclidean) — *except* where a table fixes Repeats/Pulses for the target |
| Pitch        | C3 (single note)                                                           |
| Division     | 1/16                                                                       |
| Cycles       | 1                                                                          |
| Velocity     | default (centre)                                                           |
| Sustain      | default (centre)                                                           |
| Probability  | default (off / centre)                                                     |
| Scale / Root | Chromatic / C                                                              |
| Style        | default (poly, VB1)                                                        |
| MIDI channel | 1                                                                          |

> **Optional free cross-check (costs nothing):** set this bank's **Tempo** to a distinctive value
> (e.g. **150 BPM**). Tempo is already decoded as bank-summary bytes 0–1; a non-default value
> re-confirms it for free in the same backup.

---

# BANK 0 — Open items

- [ ] **BANK 0 programmed & saved**

One Pattern per open item. Base Track as above; only the named column changes per track.

---

### - [X] P1 — Custom encoder CC# (reassign an encoder's CC number)

**Isolates:** the literal **CC-number byte** for a CC-mode encoder. B23 only ever used the default
mapping (CC# = 70 + encoder index), so we know the *enable flag* (`steps+0x16b` + `0x17`·N) and the
*value* (`steps+0x155` + `0x17`·N) but **not** where a *reassigned* CC number is stored. Reassigning
encoder 0's CC# in a clean ladder makes that byte count monotonically.

**Setup:** every track in **CC mode**; enable **encoder 0** only; leave its **encoder value fixed**
(Base / default) so only the CC-number byte moves. Then set encoder 0's **CC number** one notch per
track. Use a contiguous ladder that crosses the default 70 (so we can also confirm the default isn't
a special-cased value).

| Track | Mode | Encoder | CC value (fixed) | CC number |
| ----- | ---- | ------- | ---------------- | --------- |
| 1     | CC   | enc 0   | default          | 64        |
| 2     | CC   | enc 0   | default          | 65        |
| 3     | CC   | enc 0   | default          | 66        |
| 4     | CC   | enc 0   | default          | 67        |
| 5     | CC   | enc 0   | default          | 68        |
| 6     | CC   | enc 0   | default          | 69        |
| 7     | CC   | enc 0   | default          | 70        |
| 8     | CC   | enc 0   | default          | 71        |
| 9     | CC   | enc 0   | default          | 72        |
| 10    | CC   | enc 0   | default          | 73        |
| 11    | CC   | enc 0   | default          | 74        |
| 12    | CC   | enc 0   | default          | 75        |
| 13    | CC   | enc 0   | default          | 76        |
| 14    | CC   | enc 0   | default          | 77        |
| 15    | CC   | enc 0   | default          | 78        |
| 16    | CC   | enc 0   | default          | 79        |

> If the encoder CC# can't be reassigned freely (e.g. only a fixed list is offered), just step
> through whatever distinct CC numbers the device lets you choose, one per track, **monotonically**,
> and note the exact list you used below.

**Notes / anything done differently:** _________________________________________________

---

### - [X] P2 — Ramp, positive half (centre → full-positive)

**Isolates:** the **positive granularity** of Ramp (`steps+0x13b`, s8 bipolar). The negative half is
already mapped; here we start at **centre (0)** and climb **+1 notch per track** to full-positive so
the stored byte's positive steps are sampled densely.

**Fixed:** **Repeats = 4** on every track (Ramp only shapes a repeat burst). Ladder Ramp only.

| Track | Repeats (fixed) | Ramp                       |
| ----- | --------------- | -------------------------- |
| 1     | 4               | centre (0)                 |
| 2     | 4               | +1 notch                   |
| 3     | 4               | +2                         |
| …     | 4               | … (one notch up per track) |
| 16    | 4               | full positive (top)        |

**Notes / anything done differently:** _________________________Swep did not reach max, had to jump from Track 15 to max on Track 16________________________

---

### - [X] P3 — Pace, positive half (centre → full-positive)

**Isolates:** the positive granularity of Pace (`steps+0x13c`, s8 bipolar). Same shape as P2.

**Fixed:** **Repeats = 4** on every track.

| Track | Repeats (fixed) | Pace                |
| ----- | --------------- | ------------------- |
| 1     | 4               | centre (0)          |
| 2     | 4               | +1 notch            |
| 3     | 4               | +2                  |
| …     | 4               | …                   |
| 16    | 4               | full positive (top) |

**Notes / anything done differently:** _________________________Swep did not reach max, had to jump from Track 15 to max on Track 16________________________

---

### - [X] P4 — Range, positive half (centre → full-positive)

**Isolates:** the positive granularity of Range / pitch-variation amount (`steps+0x90`, s8 bipolar).
B21 had one noise collision and only the negative half, so a clean positive sweep also re-confirms
the offset.

| Track | Range               |
| ----- | ------------------- |
| 1     | centre (0)          |
| 2     | +1 notch            |
| 3     | +2                  |
| …     | …                   |
| 16    | full positive (top) |

**Notes / anything done differently:** _________________________Swep did not reach max, had to jump from Track 15 to max on Track 16________________________

---

### - [X] P5 — Voicing (amount), positive half (centre → full-positive)

**Isolates:** the positive granularity of the Voicing **motion-amount** byte (`steps+0xcf`, s8
bipolar — distinct from Style `steps+0x13d`). Keep **Style fixed at default (poly, VB1)** so only the
amount byte moves.

| Track | Style (fixed) | Voicing amount      |
| ----- | ------------- | ------------------- |
| 1     | poly VB1      | centre (0)          |
| 2     | poly VB1      | +1 notch            |
| 3     | poly VB1      | +2                  |
| …     | poly VB1      | …                   |
| 16    | poly VB1      | full positive (top) |

**Notes / anything done differently:** _________________________Swep did not reach max, had to jump from Track 15 to max on Track 16________________________

---

### - [X] P6 — Accent (amount), positive half (centre → full-positive)

**Isolates:** the positive granularity of Accent (`steps+0x10f`, s8 bipolar; per-step lock id `0x18`).
Give the base a **3-note chord (C3-E3-G3)**, identical on every track, so accent has notes to act on.

| Track | Pitch (fixed) | Accent              |
| ----- | ------------- | ------------------- |
| 1     | C3-E3-G3      | centre (0)          |
| 2     | C3-E3-G3      | +1 notch            |
| 3     | C3-E3-G3      | +2                  |
| …     | C3-E3-G3      | …                   |
| 16    | C3-E3-G3      | full positive (top) |

**Notes / anything done differently:** _________________________Swep did not reach max, had to jump from Track 15 to max on Track 16________________________

---

### - [X] P7 — Repeat choke vs tail (isolate the two modes)

**Isolates:** the semantics of the repeater end-behaviour byte at `steps+0x14a`. B25 set choke and
tail **together** on one track and saw only the value `1`, so we can't tell whether `+0x14a` is a
**bitfield** (off=0, tail=1, choke=2, both=3 — or the reverse) or a single **enum**. This pattern
programs each combination on its own track so the four byte values separate cleanly.

**Fixed:** **Repeats = 4** on every track (the repeater must be active for choke/tail to matter).
This is **not** a ladder — it is four distinct mode combinations, one per track.

| Track | Repeats (fixed) | Repeat end-behaviour                          |
| ----- | --------------- | --------------------------------------------- |
| 1     | 4               | neither (choke OFF, tail OFF) — baseline      |
| 2     | 4               | **tail ON only** (choke OFF)                  |
| 3     | 4               | **choke ON only** (tail OFF)                  |
| 4     | 4               | **both ON** (choke + tail) — matches B25's T1 |

> "Choke" and "Tail" are best-guess panel names for the two repeater end-behaviour toggles on the
> **Repeat** page; if the device labels them differently, note the exact control names you toggled
> below so we can map value → label. Leave Tracks 5–16 empty.

**Notes / anything done differently:** _________________________Its xor: tail xor choke, never both, never none, i did tracks 1&2 tail on, tracks 3&4 choke on________________________

---

### - [X] P8 — Retrigger steps (monotonic ladder)

**Isolates:** the per-track **retrigger** field — **not exercised in any earlier backup**, so its
offset is completely unknown. Step the retrigger amount/count up one notch per track so the byte
counts monotonically and pops out of the diff.

| Track | Retrigger steps            |
| ----- | -------------------------- |
| 1     | 0 / off (lowest)           |
| 2     | +1 notch                   |
| 3     | +2                         |
| …     | … (one notch up per track) |
| 16    | highest                    |

> ⚠️ **Control name uncertain.** "Retrigger steps" is the description from the decode TODO; the exact
> T-1 panel control isn't confirmed (it is **not** the already-decoded **Repeats** at `steps+0xfa` —
> please keep Repeats at the Base default of 4 here so the two don't collide). Best guess: a per-track
> retrigger / ratchet-style control. **Please write down exactly which control you laddered, its label,
> and its min/max** in the Notes line — that mapping is the main thing we need from this pattern. If the
> control turns out to be bipolar, ladder full-negative → full-positive instead and say so.

**Notes / anything done differently:** _________________________This is not a parameter with a value. A retrigger step can be placed on every step and will retrigger random sequence, accent, groove, etc. For Tracks 1 to 8 I placed a retrigger step on Step 1 to 8, for tracks 9 to 16 i placed retrigger steps on 1, 1&2, 1&2&3, .. 1&2&3&4&5&6&7&8________________________

---

## After programming — what to send

1. **Manual-save** each pattern you edited in Bank 0.
2. **Backup → export** the full backup zip (all 8 banks).
3. Send that single zip. It contains Bank 0 with all four open items — everything needed to close out
   the remaining undecoded fields in one pass.

### What we'll do with it (for reference)

We align Bank 0's track blocks and run `t1_blockdiff.py --sweep` per pattern; the laddered byte that
counts `1,2,3,…` is the field:

- **P1** → the reassigned **CC-number** byte (expected near the encoder array `steps+0x155…+0x296`,
  stride `0x17`; we'll confirm whether it's a separate byte or a remap of the enable flag `+0x16b`).
- **P2–P6** → the **positive-half scale/granularity** of the five bipolar s8 params (`+0x13b` Ramp,
  `+0x13c` Pace, `+0x90` Range, `+0xcf` Voicing, `+0x10f` Accent) — pins down step size and range above 0.
- **P7** → the **choke/tail** semantics at the known offset `steps+0x14a` (bitfield vs enum, and which
  value is which mode).
- **P8** → locates the **retrigger** byte (new offset).

Each decoded field then gets a `decode/samples/NN_*` reference, a byte-exact rebuild proof
(`decode/test_decode.py`), and — once confirmed — a line in canonical `FORMAT.md`.





I added pattern 9, where i selected tracks 1 to 4 
pattern 10, where i selected tracks 5 to 8
and pattern 11, where i selected tracks 9 to 12 to confirm selection cursor for multiple tracks.
