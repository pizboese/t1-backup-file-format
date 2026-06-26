# `decode/` — complete-format-decode sandbox

Quarantined working area for the campaign to account for **every byte** of the `.t1` block
(see the root plan + `FORMAT_DECODE.md`). Lives only on branch **`completeDecode`**.

**Why a separate subtree.** The shipped toolchain on `main` (`t1_format.py`, `midi_to_t1.py`,
`t1_to_midi.py`, `test_roundtrip.py`, `samples/`) is hardware-verified and must stay green and
uncluttered. The decode campaign acquires raw backups whose new fields aren't modeled yet — a
fresh sample would turn `test_roundtrip.py`'s "ALL PASS" red if it joined the shared `samples/`
glob. So everything campaign-related is isolated here.

## Contents
- `samples/NN_*/` — campaign backups (extracted `.t1` + a notes file: programmed values, LED
  readings, what each one decodes). **Kept out of the root `samples/` glob on purpose.**
- `test_decode.py` — roundtrip over `decode/samples/**` only. Reuses `test_roundtrip.test_file`.
  **Allowed to be red** on a field we've located but not yet modeled — that's the campaign's TODO,
  not a regression.
- `FORMAT_DECODE.md` — the live scoreboard (Part-1 inventory) + per-field decode notes.
- `t1_decode.py` — additive field reporting layered on top of `t1_format` (`import t1_format as F`).
  New parsing goes here so edits to the shipped `t1_format.py` stay minimal and additive.

## Ground rules
- **Never break `main`'s working set.** Edits to `t1_format.py` are additive (new reported fields
  only); `test_roundtrip.py` must stay ALL PASS as the regression guard.
- **Branch is a permanent fork.** Only *confirmed* findings get folded into the canonical `FORMAT.md`
  / `CLAUDE.md` and cherry-picked back to `main` (docs only). Tooling/code stays here.
- Confirm a decoded field by: adding its sample under `decode/samples/`, getting `test_decode.py`
  to rebuild it byte-for-byte, and having `t1_decode.py` report the programmed ladder.

## Run
```
python3 decode/test_decode.py          # roundtrip the campaign samples
python3 decode/t1_decode.py FILE.t1     # parse + report decoded/located fields
```
