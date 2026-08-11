# Torso T-1 backup format (`.t1`) ⇄ MIDI

Reverse-engineering the [Torso Electronics **T-1**](https://torsoelectronics.com/) sequencer's
backup format so patterns can be **exported to** and **imported from** standard MIDI files — and
so a bank can be rebuilt from scratch and loaded back onto the hardware.

The format is fully worked out for the musically meaningful fields: every archived device backup in
this repo **rebuilds byte-for-byte**, and synthesized banks (chords, cycles, split drum kits) have
been **loaded and verified on real T-1 hardware**.

> ### Built with Claude Code
> This project — the reverse engineering, the byte-map, the tooling, and this documentation — was
> produced through **heavy use of [Claude Code](https://claude.com/claude-code)** (Anthropic).
> The workflow was collaborative: the hardware owner captured device backups on request (targeted
> parameter sweeps), and Claude Code diffed them, located the fields, wrote the codecs, and drove
> the round-trip and on-device verification. It is genuinely an AI-assisted RE effort, not a
> hand-written library, and the commit history reflects that.

---

## What this is

The T-1 has no documented save format. Its **backup** is a ZIP whose banks are opaque binary blobs.
This repo decodes that blob into a clean data model and back again:

```
 .t1 bank  ──▶  t1_format.py  ──▶  { patterns: [ [track, …], … ] }   (parse / decode)
    ▲                                          │
    │                                          ▼
 midi_to_t1.py  ◀── .mid files          t1_to_midi.py ──▶ .mid files  (import / export)
    │                                          ▲
    └────────── rebuilds a device-loadable backup zip ──────────────┘
```

**What's decoded** (see [`FORMAT.md`](FORMAT.md) for the full byte-map):

- Container layout — bank header, sparse 803-byte track blocks, pattern gaps, trailer, and the two
  ZIP shapes the device restores (full 8-bank backup / fresh single-bank file).
- Per-step **gates**, absolute **pitch** (incl. **chords** via multi-note pitch locks), **velocity**
  and **sustain** (with the device's real value scales), per-step **locks** (pitch/velocity/length).
- Track **routing** (MIDI channel/mask), **root**, **scale**, **division/timing**.
- **Cycles** — up to 16 per track, with per-cycle pitch/param/step-sequence overrides.
- **Steps up to 64**, sparse **track positions** (fixed slots with gaps), and the drum-kit layout.
- **Backup-1 parameters** — Tempo, per-track Length, Probability, Timing (swing) + subdivision,
  Delay, Quantize, and the free/fixed-division flag.

The format has **no checksum** (proven by successful on-device import), which is what makes
faithful rebuilding possible.

---

## Repository layout

| Path | What it is |
|---|---|
| [`FORMAT.md`](FORMAT.md) | The byte-map — read this to understand the format. Container, lock terminators, cursor/summary, stored-state region, cycles, track positions, backup-1 fields. |
| `t1_format.py` | **Parser** (`parse_bank(path)` → data model). |
| `t1_to_midi.py` | **Exporter** — `.t1` → one `.mid` per pattern. |
| `midi_to_t1.py` | **Importer** — `.mid` → a device-loadable `.t1` / backup zip. |
| `t1_cycles.py` | Decoder/printer for the steps-to-64 + **cycles** feature. |
| `test_roundtrip.py` | Self-test: rebuilds every archived bank byte-for-byte. |
| `t1_annotate.py`, `t1_blockdiff.py` | RE helpers (byte diff / monotonic-sweep field finder). |
| `make_*.py` | One-off builders that synthesize hardware-verification banks/MIDI. |
| `samples/` | Archived device backups — the experimental record. Each folder decoded part of the format; see [`samples/README.md`](samples/README.md). |
| `hwtest/` | Hardware-verification working set, incl. `fromT1/` device-authored ground-truth files. |
| `decode/` | The "complete decode" campaign — extra tooling, notes, and sweep samples pushing byte coverage toward 100%. |
| `CLAUDE.md` | Project status + working notes (also the guide the AI assistant follows). |

---

## Requirements

**Python 3, no third-party dependencies.** (MIDI reading/writing and ZIP handling use the standard
library only.) A real T-1 is only needed if you want to load results onto hardware.

---

## Usage

### Inspect a bank

```bash
python3 t1_format.py samples/09_perstep_polyphony/bank.t1
```
Prints the decoded tracks, per-step locks, cycles, and each track's slot position.

### Export `.t1` → MIDI

```bash
python3 t1_to_midi.py FILE.t1 -o OUTDIR [--bpm 120]
```
Writes one Type-1 `.mid` per non-empty pattern at **96 PPQN** (the device's resolution). Without
`--bpm` it uses the bank's stored tempo. Exports gates, per-track division/timing, track pitch +
chords, per-step pitch/velocity/sustain locks, multi-channel routing, root and scale.

### Import MIDI → `.t1`

```bash
python3 midi_to_t1.py -o OUT.t1 IN1.mid [IN2.mid …] [options]
```

Each `.mid` becomes one pattern; each MIDI channel (or SMF track, with `--split-tracks`) becomes one
track. Chords and pitch changes become **pitch locks**; per-step velocity / note-length become
**groove locks**. Notes are quantized to the step grid (max 16 patterns × 16 tracks).

Common options:

| Option | Effect |
|---|---|
| `--div N` | Grid/playback division (default 16). |
| `--length N` | Loop length in steps, 1–16 (single-cycle mode). |
| `--split-tracks` | Map each SMF track (not each channel) to a T-1 track. |
| `--drum-split` | Explode a drum part into one T-1 track per GM sound on fixed slots (kick=16, snare=15, hats=14/13, clap=12, …). |
| `--cycles auto\|bars\|off` | Cycle handling. `auto` (default): a voice spanning >1 window becomes cycles; `bars`: always map each `--steps`-window k → cycle k; `off`: single cycle. |
| `--steps N` | Steps per cycle/track, 1–64 (default 16). |
| `--tempo BPM` | Bank tempo (default 120). |
| `--track-length`, `--timing`, `--delay` | Per-track Length / swing / shift (backup-1 fields). |
| `--zip BACKUP.zip --slot N` | Emit `OUT.zip` by splicing the bank into a **real** backup (non-destructive). |
| `--new-backup --slot N` | Emit `OUT.zip` as a fresh single-bank backup (only that bank is touched on restore). |

Two placement helpers: `--by-filename` derives placement from names like `pattern1_track2.mid`, and
`--plan FILE.json` gives an explicit per-pattern/per-track table (the most general form).

### Cycles view

```bash
python3 t1_cycles.py FILE.t1
```
Prints per-track cycle count, step-group page, per-cycle track-pitch overrides, and per-cycle
step-sequence records (gate + per-step locks).

---

## Loading results onto the T-1

The device restores a **backup ZIP** via its Backup menu. Two shapes work (both emitted by the
importer — no manual zipping):

- **Fresh single-bank file** (`--new-backup --slot N`) — restoring it overwrites **only** that one
  bank and leaves the other 7 intact. This is the truly non-destructive path.
- **Spliced full backup** (`--zip REAL_BACKUP.zip --slot N`) — replaces one slot inside a real
  backup you exported; the other banks and settings stay byte-identical.

Every entry must be `ZIP_STORED` (uncompressed) with the exact `./`-prefixed layout the device
expects; the tooling handles this. See `CLAUDE.md` / `FORMAT.md` for the exact recipe and rules.

> ⚠️ **Back up your device first.** These are unofficial, reverse-engineered tools. A malformed bank
> is rejected by the device (and can trigger a bank re-initialization), so always keep a known-good
> backup and prefer the single-bank path while experimenting.

---

## Verifying

```bash
python3 test_roundtrip.py     # expect: ALL PASS
```
Rebuilds every archived sample bank byte-for-byte — run it after any change to the parser or to
block/container synthesis. Beyond this, synthesized banks (chords, velocity/sustain, cycles, and
drum-split kits) have been loaded and confirmed on real T-1 hardware; the working set lives in
`hwtest/`, with device-authored ground-truth references in `hwtest/fromT1/`.

---

## Status & scope

The musically meaningful format is decoded and hardware-verified in both directions. Remaining work
is polish and edge decoding — e.g. exact tick units for Timing/Delay, MIDI→scale/root mapping
(currently Chromatic/C so absolute pitch plays), and a few interior bytes of the CC-encoder and
modulation records. See `CLAUDE.md` and `decode/` for the current frontier.

## License

[MIT](LICENSE) © 2026 Sebastian Hasinger.

Torso® and T-1 are trademarks of Torso Electronics. This is an independent, unofficial
reverse-engineering project and is not affiliated with or endorsed by Torso Electronics.
