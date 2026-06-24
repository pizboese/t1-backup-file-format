# 20 — Backup-1 parameter sweep (Timing, Delay, Probability, Length, Quantize, Free-div, Tempo)

First backup of the "decode every remaining bit" campaign (plan: import-critical timing/feel first).
Source: `backup1.zip` (one full backup). Method: **one parameter per Pattern**, the same base track
(16 steps, all pulsed, C3, defaults) **copied** across 16 tracks with only the target laddered, so
the 16 blocks differ in exactly the target byte + the position end-marker — the cleanest possible
diff. Decoded with `t1_blockdiff.py --steps-only`.

`0.t1` = the test bank (UI Bank 1, tempo 120):

| Pattern | Param | Field (steps-rel) | Result |
|--------|-------|-------------------|--------|
| P1 | Timing (swing amount) | `+0x0ba` | signed int8, center 0 (random run `+0xbb`) |
| P2 | Delay (track shift)   | `+0x13e` | signed int8, center 0 (static) |
| P3 | Length (track loop)   | `+0x14b` | enum 0–15: 0=1bar(def),1–7=2–8bar,8=∞,9=1/2,10=1/4,11=1/8,12=1/16,13=1/32,14=1/64,15=16bar |
| P4 | Probability           | `+0x079` | signed int8, center 0 (−=pulses only, +=all notes) |
| P5 | Free Division (8 trk) | `+0x299` flag | 0=fixed/1=free; division **value** stays the `+0x2a` u16 |
| P6/P7/P8 | Quantize (VB1/8/16) | pattern-trailer 4th byte | 11/0/15 → 1/8 bar / 1 bar / 16 bar (same enum as Length); per-pattern, not in the block |
| P9 | (per-step Timing lock) | — | **could not be entered on device**; left as a plain track |

`1.t1` = tempo **24** (`18 00`), `2.t1` = tempo **280→278** (`16 01`) — single default track each,
proving **Tempo = bank-summary bytes 0–1, u16 LE BPM** (the old "constant `0x78`" was default 120).

`3.t1` = UI Bank 4: **Timing subdivision** /1,/2,/4 on tracks 1/2/3 → `steps+0x146` = 4/5/3.

Full byte-map + the tempo/quantize corrections are in FORMAT.md "Backup-1 decode". These are all
display/value fields — `test_roundtrip.py` was already byte-exact and stays **ALL PASS**.
