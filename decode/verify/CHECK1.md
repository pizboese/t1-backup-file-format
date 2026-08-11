# Round 1 — on-device findings (preserved)

This is the user's original CHECK.md from round 1 (verify_findings.zip), preserved here
after the auto-generated CHECK.md was overwritten. Round 1 used the buggy `end_mark = i+2`
builder, which is why every bank shows the +1 slot shift; see CHECK2.md for round 2.

## Bank 0 — SHAPE

| ✓   | Track | Parameter             | Expected on device           | Notes / caveats                                       |
| --- | ----- | --------------------- | ---------------------------- | ----------------------------------------------------- |
| ☐   | T1    | Steps                 | Steps = 12                   | Bank0 does not load on device, stays empty, has error |
| ☐   | T2    | Pulses                | Pulses = 8 (of 16)           |                                                       |
| ☐   | T3    | Rotate                | Rotate = 3                   |                                                       |
| ☐   | T4    | Repeats               | Repeats = 6                  |                                                       |
| ☐   | T5    | Ramp                  | Ramp ~ +12 (right of centre) |                                                       |
| ☐   | T6    | Time (repeat spacing) | Time = 1/16                  |                                                       |
| ☐   | T7    | Pace                  | Pace ~ +12                   |                                                       |
| ☐   | T8    | Range                 | Range ~ +12                  |                                                       |
| ☐   | T9    | Phrase shape          | Phrase shape = 4th (index 3) |                                                       |
| ☐   | T10   | Phrase length         | Phrase length = 8 bars       |                                                       |
| ☐   | T11   | Voicing amount        | Voicing amount ~ +12         |                                                       |
| ☐   | T12   | Voicing direction     | Voicing direction = Down     |                                                       |
| ☐   | T13   | Style                 | Style = mono/arp (index 8)   |                                                       |
| ☐   | T14   | Cycles                | Cycles = 8                   |                                                       |
| ☐   | T15   | Division              | Division = 1/8               |                                                       |
| ☐   | T16   | Division FREE         | Division in FREE mode        |                                                       |

## Bank 1 — GROOVE

| ✓   | Track | Parameter               | Expected on device                           | Notes / caveats                                                                        |
| --- | ----- | ----------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------- |
| ☐   | T1    | Velocity + step lock    | Velocity ~96; step5 high(127), step9 low(40) | Bank1 does not load on device, stays empty, has error                                  |
| ☐   | T2    | Probability             | Probability ~ +12                            |                                                                                        |
| ☐   | T3    | Sustain + step lock     | Sustain ~96; step5 short(32)                 |                                                                                        |
| ☐   | T4    | ⚠️ Timing (swing) + sub | Timing ~ +12, subdivision toggled            | subdivision 3-point enum unconfirmed; wrote sub=1 — just check it differs from default |
| ☐   | T5    | Delay                   | Delay ~ +12                                  |                                                                                        |
| ☐   | T6    | ⚠️ Accent (track)       | Accent ~ +12                                 | only the TRACK accent; the per-step accent lock (id 0x18) is not authored here         |
| ☐   | T7    | Groove pattern          | Groove pattern = 4th (index 3)               |                                                                                        |
| ☐   | T8    | Groove length           | Groove length = 8 bars                       |                                                                                        |
| ☐   | T9    | Repeat Choke/Tail       | Repeater = CHOKE (Repeats=6)                 |                                                                                        |

## Bank 2 — TONAL

| ✓   | Track | Parameter     | Expected on device                               | Notes / caveats |
| --- | ----- | ------------- | ------------------------------------------------ | --------------- |
| ok  | T1    | Scale preset  | Scale = Major                                    |                 |
| no  | T2    | Root          | Root = G                                         | tOK but on T3   |
| no  | T3    | ⚠️ Harmony    | Harmony value = 3 (stored pitches C-E-G)         | OK but on T4    |
| no  | T4    | Custom scale  | Scale = Custom; degrees C D# F G A# (minor pent) | OK but on T5    |
| no  | T5    | Chord default | Track plays C major chord (no per-step lock)     | OK but on T6    |

## Bank 3 — MODES / ROUTING

| ✓   | Track | Parameter                   | Expected on device                | Notes / caveats |
| --- | ----- | --------------------------- | --------------------------------- | --------------- |
| ok  | T1    | Track Mode = CC + encoder   | Mode=CC; enc0 -> CC#74, value ~64 |                 |
| no  | T2    | Track Mode = FX             | Mode = FX                         | OK but on T3    |
| no  | T3    | Internal routing            | Routed internally to track 3      | OK but on T4    |
| no  | T4    | Mute                        | Track is MUTED                    | OK but on T5    |
| no  | T5    | MIDI channel                | Output channel = 5                | OK but on T6    |
| no  | T6    | Track Mode = Note (control) | Mode = Note (default)             | OK but on T7    |

## Bank 4 — GLOBAL / RANDOM

_Bank-level:_ Tempo = 132 BPM; Quantize enum=3 seems to be so

| ✓   | Track | Parameter                     | Expected on device                   | Notes / caveats                                                                                                                                                 |
| --- | ----- | ----------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ok  | T1    | Track Length                  | Loop length = 2 bars                 |                                                                                                                                                                 |
| no  | T2    | Rate                          | Rate = 1/8                           | OK but on T3                                                                                                                                                    |
| no  | T3    | Random intensity              | Random intensity = 8/16              | OK but on T4                                                                                                                                                    |
| no  | T4    | Random amount+lock (velocity) | Velocity random amount ~ +12, locked | OK but on T5                                                                                                                                                    |
| no  | T5    | Retrigger (per-step)          | Steps 3 & 4 retrigger (subdivide)    | OK but on T6                                                                                                                                                    |
| OK  | T6    | ⚠️ Track selection cursor     | Pattern opens with track 3 selected  | only the SINGLE saved cursor is authored (which track the pattern opens on); the multi-track selection SET (the under-emitted extended trailer) is NOT authored |

## Free-form notes / observations

somehow every track two is empty, then the following are +1

banks 0 and 1 have errors and dont load

there are empty banks 5,6,7_
