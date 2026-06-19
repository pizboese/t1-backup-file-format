# 14 — trailing lock-summary (the real chord blocker)

**Source:** `iteration3.zip` (device backup, slot 0). Extracted bank: `iteration3.t1`.

**Setup (device):** two patterns of identical chord-lock tracks — P1: 3 tracks (ch 1/2/3),
P2: 2 tracks (ch 1/2). Each track: C–E–G per-step pitch lock on steps 1/5/9/13, **entered in
step order 1→5→9→13** (so newest lock = step 13 = 0-based 12). Designed to expose the trailing
lock-summary across every block position and a controlled lock-entry order.

**Background:** masking the 29 known random runs out of a `hwtest.t1` (broken) vs
`hwtest_handtmpl.t1` (working) diff left a single structural difference: a trailing summary at
`steps+0x29c`. Broken bank (non-lock template cloned for a lock-bearing block) had it ZEROED.

**Result (per block):** A(`+0x29c`)=1 on all (incl. final); K(`+0x2a0`)=**12** on all (= newest
locked step); end-marker `+0x2b5/+6` = `00 01` except block1 = `00 02`.

**Decoded — the summary is per-block UI/cursor state, NOT structural linkage:**
- `+0x29c` (A) = 1 when locks present (the `01 00 00 00 <K> 00` record exists). Zero = non-lock.
- `+0x2a0` (K) = newest-stored / last-edited lock step (cursor). Confirmed: all blocks here = 12.
- `+0x2b5/+0x2b6` = `00 01` end-marker (varies to `00 02` as cursor state).
- A lock-bearing block must have this summary PRESENT; the device rejects a zeroed one (the
  broken-bank failure). Exact values are saved-UI-state — any valid in-range values load.

**Validation:** rebuilding each device block from the generic non-lock template via
`midi_to_t1.build_track_block` reproduces the device's block byte-for-byte on every non-random
byte (4/5 exact; block1 differs only in the `+0x2b6` UI byte). → importer fix is device-equivalent.

**Fix:** `midi_to_t1.build_track_block` now writes the summary (A=1, K=max locked step,
end-marker `00 01`) when a lock block uses a non-lock template. Roundtrip stays byte-exact.
Pending: on-device load test of a fully-synthesized bank.
