# 12 — random re-roll (carve steps-region into [random | params])

**Source:** `iteration1.zip` (device backup, slot 0 only). Extracted bank: `iteration1.t1`.

**Setup (device):** one track (pulses 1/5/9/13, vel 100, sus 63, ch 1, Random amount 0),
copied across 4 patterns. Per copy, re-rolled exactly ONE parameter's random sequence:
- P1 (block 0) = baseline
- P2 (block 1) = **Pitch** random re-rolled
- P3 (block 2) = **Velocity** random re-rolled
- P4 (block 3) = **Sustain** random re-rolled

**Analysis:** `python3 t1_blockdiff.py samples/12_random_reroll/iteration1.t1`

**Result:** only 51 bytes changed, in 3 runs of exactly 17 bytes — one per re-rolled param:
| param    | odd-one-out block | steps-offset of its 17-byte random seq |
|----------|-------------------|----------------------------------------|
| Pitch    | block 1 (P2)      | `steps+0x055`                          |
| Velocity | block 2 (P3)      | `steps+0x07c` (value `0x64`=100 at +0x7b) |
| Sustain  | block 3 (P4)      | `steps+0x0a6` (value `0x3f`=63 at +0xa5)  |

**What it decoded** (see FORMAT.md "Steps-region carved into TWO zones"):
- **Zone A** (`steps+0x00..~0x150`) = per-track parameter table of `<value> <17-B random seq>`
  records, value-first. ~15 random seqs; the value bytes between them hold the params.
- **Zone B** (`steps+0x150..0x296`) = `00 00 00 <id> 00 64 <17 B>` array (ids 0x46–0x52); did
  NOT change on re-roll → not the track random buffer (per-step/locked-random state).
- Copy-pattern preserves random; per-parameter re-roll is surgical; re-roll works at Random=0.

**Next:** value-sweep for the **Style/Voicing** field (chord blocker) — it's a value slot, not
a random seq, so re-roll won't find it. Then re-roll the remaining ~8 params to name every seq.
