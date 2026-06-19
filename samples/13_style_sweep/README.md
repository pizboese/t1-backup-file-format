# 13 — Style (voicing) sweep

**Source:** `iteration2.zip` (device backup, slot 0). Extracted bank: `iteration2.t1`.

**Setup (device):** one track with a 3-note chord default (C–E–G, pc=3), pulses 1/5/9/13,
copied across 10 patterns. Style set per pattern to the 10 variants in order:
P1–P5 = VB1..VB5 (polyphonic), P6–P10 = VB9..VB13 (monophonic). Voicing left at 0.

**Analysis:** `python3 t1_blockdiff.py --sweep samples/13_style_sweep/iteration2.t1`

**Result:** exactly ONE byte changed across all 10 patterns — **`steps+0x13d`** —
values `[0,1,2,3,4, 8,9,10,11,12]` = `VB_index − 1`.

**Decoded:** **Style @ `steps+0x13d`**: polyphonic (chord) = 0–4, monophonic (arp) = 8–12;
Fixed-poly = 0. (Voicing = motion amount, a separate value, not yet located.) Importer should
write 0 for block chords. NOTE: Style turned out **NOT** to be the chord blocker — both the
broken and working hwtest banks already had Style=0 (see `14_lock_summary`).
