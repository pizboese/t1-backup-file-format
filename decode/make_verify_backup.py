#!/usr/bin/env python3
"""Build a device-loadable backup that exercises the decode-campaign findings in the
WRITE direction, so the owner can confirm on hardware that we author each field correctly.

The campaign decoded every field in the READ direction (device -> bytes). This tool does the
inverse: it SYNTHESIZES blocks (the hardware-proven midi_to_t1 path) and patches each decoded
`steps+offset` / header / gate field to a chosen, easy-to-read MID value, spread across banks
(= device pages), patterns and tracks. A matching CHECK.md is emitted so the owner can tick
each finding off and jot notes.

Layout (chosen with the owner): a FULL backup (banks 0-7 + Settings/Wifi cloned from a real
backup so restore is the canonical, definitely-supported shape). Banks 0-4 carry tests grouped
by device page; banks 5-7 stay empty. Values are MID/readable (not pegged) unless a field only
has a couple of states.

Run:  python3 decode/make_verify_backup.py
Out:  decode/verify/verify_findings.zip  +  decode/verify/CHECK.md  (+ the per-bank .t1)
"""
import json
import os
import struct
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import t1_format as F
import midi_to_t1 as M
import decode.decode_rebuild as R

OUTDIR = os.path.join(ROOT, "decode", "verify")
BASE_BACKUP = os.path.join(ROOT, "hwtest", "fromT1", "original_backup.zip")


def _next_round():
    """Pick the next round number N by scanning CHECK*.md / verify_findings*.zip in OUTDIR."""
    import re
    rx = re.compile(r"^(?:CHECK|verify_findings_?)(\d+)(?:\.md|\.zip)$")
    used = []
    if os.path.isdir(OUTDIR):
        for n in os.listdir(OUTDIR):
            m = rx.match(n)
            if m:
                used.append(int(m.group(1)))
    return (max(used) + 1) if used else 1

TPL = M.load_template(M.DEFAULT_TEMPLATE)

# steps-region fields that build_track_block ALWAYS overwrites (so we must route them through
# kwargs, not the raw-patch dict, or they'd be clobbered):
KW_FIELDS = {"steps", "division", "scale", "root", "velocity", "sustain", "mask",
             "cycles", "length", "timing", "delay", "probability", "timing_sub",
             "free_division"}

# kind -> (width, signed)
KINDS = {"u8": (1, False), "s8": (1, True), "u16": (2, False)}


def _bake(sr, off, value, kind):
    """Write a value into a copy of the steps-region at a steps-relative offset."""
    w, signed = KINDS[kind]
    if kind == "u16":
        struct.pack_into("<H", sr, off, value & 0xFFFF)
    else:
        sr[off] = value & 0xFF


def make_block(spec):
    """Synthesize one track block from a test spec (see the bank table below)."""
    # 1. bake raw steps-region patches into a private template copy
    sr = bytearray(TPL[1])
    for off, (val, kind) in spec.get("sp", {}).items():
        _bake(sr, off, val, kind)
    template = (TPL[0], bytes(sr))

    # 2. synthesize the block via the proven builder (handles gate/locks/cycles/container fields)
    kw = dict(steps=spec.get("steps", 16), division=spec.get("division", 24),
              scale=spec.get("scale", 0), root=spec.get("root", 0),
              velocity=spec.get("velocity", 100), sustain=spec.get("sustain", 64),
              mask=spec.get("mask", 1), cycles=spec.get("cycles", 4))
    for k in ("length", "timing", "delay", "probability", "timing_sub", "free_division"):
        if k in spec:
            kw[k] = spec[k]
    for k in ("cycle_pitch", "cycle_params", "cycle_records"):
        if k in spec:
            kw[k] = spec[k]
    if "cycle_records" in kw:
        # Each record's gate is given as a list of active step indices; expand to a 64-byte
        # array in the DEVICE-faithful encoding (active = bit 0x02), matching the base gate so
        # the whole block is internally consistent with the firmware the user's device runs.
        kw["cycle_records"] = [
            (cyc, [2 if i in set(g_idx) else 0 for i in range(M.GATE_LEN)], cg, cp)
            for cyc, g_idx, cg, cp in kw["cycle_records"]]
    active = spec.get("gate", [0, 4, 8, 12])
    gate01 = [1 if i in active else 0 for i in range(M.GATE_LEN)]
    blk = bytearray(M.build_track_block(
        template, gate=gate01, pitches=spec.get("pitches", [60]),
        pitch_locks=spec.get("pitch_locks", {}), groove_locks=spec.get("groove_locks", {}),
        end_mark=spec["end_mark"], **kw))

    # 3. custom scale: replace the chromatic degree table in the header with the enabled degrees
    if "custom_scale" in spec:
        h = R.walk_header(bytes(blk), 0)
        degs = spec["custom_scale"]
        new_hdr = R._serialize_header(h["X"], h["pc"], h["pitches"], h["cyc_pitch"],
                                      len(degs), degs)
        blk = bytearray(new_hdr + bytes(blk[h["gate_start"]:]))

    # 4. gate: rewrite to the DEVICE-faithful encoding (active = bit 0x02, retrigger = bit 0x04)
    h = R.walk_header(bytes(blk), 0)
    g0 = h["gate_start"]
    retrig = set(spec.get("retrig", []))
    for i in range(M.GATE_LEN):
        blk[g0 + i] = (2 if i in active else 0) | (4 if i in retrig else 0)
    return bytes(blk)


# ── the test plan: bank -> list of patterns -> list of track specs ───────────────────────────
# Each spec carries CHECK metadata: page/param/expect/note. `sp` = raw steps-relative patches.
# `harmony`/`mute` are post-assembly (header-adjacent) and recorded for the patch pass below.

def s(check, **spec):
    spec["check"] = check
    return spec


BANKS = {
 0: {"name": "SHAPE", "patterns": [[
    s(dict(param="Steps",            expect="Steps = 12"),                         steps=12, gate=list(range(12))),
    s(dict(param="Pulses",           expect="Pulses = 8 (of 16)"),                 sp={0x15:(8,"u8")}, gate=[0,2,4,6,8,10,12,14]),
    s(dict(param="Rotate",           expect="Rotate = 3"),                         sp={0x13a:(3,"u8")}),
    s(dict(param="Repeats",          expect="Repeats = 6"),                        sp={0xfa:(7,"u8")}),
    s(dict(param="Ramp",             expect="Ramp ~ +12 (right of centre)"),       sp={0x13b:(12,"s8")}),
    s(dict(param="Time (repeat spacing)", expect="Time = 1/8 (non-default)",
           caveat="round 3 wrote `24` = 1/16 which IS the default → indistinguishable on device; round 4 writes `48` = 1/8 so the byte placement is provable"),
      sp={0x124:(48,"u16")}),
    s(dict(param="Pace",             expect="Pace ~ +12"),                         sp={0x13c:(12,"s8")}),
    s(dict(param="Range",            expect="Range ~ +12"),                        sp={0x90:(12,"s8")}),
    s(dict(param="Phrase shape",     expect="Phrase shape = 4th (index 3)"),       sp={0x147:(3,"u8")}),
    s(dict(param="Phrase length",    expect="Phrase length = 8 bars"),             sp={0x144:(3,"u8")}),
    s(dict(param="Voicing amount",   expect="Voicing amount ~ +12"),               sp={0xcf:(12,"s8")}),
    s(dict(param="Voicing direction",expect="Voicing direction = Down"),           sp={0x149:(1,"u8")}),
    s(dict(param="Style",            expect="Style = mono/arp (index 8)"),         sp={0x13d:(8,"u8")}),
    s(dict(param="Cycles",           expect="Cycles = 8"),                         cycles=8),
    s(dict(param="Division",         expect="Division = 1/8"),                     division=48),
    s(dict(param="Division FREE",    expect="Division in FREE mode"),              free_division=1, division=24),
 ]]},
 1: {"name": "GROOVE", "patterns": [[
    s(dict(param="Velocity + step lock", expect="Velocity ~96; step5 high(127), step9 low(40)"),
      velocity=96, gate=list(range(16)), groove_locks={4:{"velocity":127}, 8:{"velocity":40}}),
    s(dict(param="Probability",      expect="Probability ~ +12"),                  sp={0x79:(12,"s8")}),
    s(dict(param="Sustain + step lock", expect="Sustain ~96; step5 short(32)"),
      sustain=96, gate=list(range(16)), groove_locks={4:{"sustain":32}}),
    s(dict(param="Timing (swing) + sub", expect="Timing ~ +12, subdivision = /2",
           caveat="subdivision enum has only 3 valid values: /1=4 (default), /2=5, /4=3. Round 2 wrote sub=1 (out of range) and crashed bank 1's load — switched to sub=5 (= /2) for round 3."),
      sp={0xba:(12,"s8")}, timing_sub=5),
    s(dict(param="Delay",            expect="Delay ~ +12"),                        sp={0x13e:(12,"s8")}),
    s(dict(param="Accent (track)",   expect="Accent ~ +12",
           caveat="only the TRACK accent; the per-step accent lock (id 0x18) is not authored here"), sp={0x10f:(12,"s8")}),
    s(dict(param="Groove pattern",   expect="Groove pattern = 4th (index 3)"),     sp={0x148:(3,"u8")}),
    s(dict(param="Groove length",    expect="Groove length = 8 bars"),            sp={0x145:(3,"u8")}),
    s(dict(param="Repeat Choke/Tail",expect="Repeater = CHOKE (Repeats=6)"),       sp={0xfa:(7,"u8"), 0x14a:(1,"u8")}),
 ]]},
 2: {"name": "TONAL", "patterns": [[
    s(dict(param="Scale preset",     expect="Scale = Major"),                      scale=1),
    s(dict(param="Root",             expect="Root = G"),                           root=7),
    s(dict(param="Harmony",          expect="Harmony value = 3 (stored pitches C-E-G)",
           caveat="LOW confidence: value byte at run-0x10 is header-relative/ambiguous, and "
                  "Harmony is an algorithmic field — storing fixed pitches does not exercise the "
                  "engine. Treat as best-effort; the clean signal is whether the value shows up at all"),
      harmony=3, pitches=[60,64,67]),
    s(dict(param="Custom scale",     expect="Scale = Custom; degrees C D# F G A# (minor pent)"),
      scale=7, custom_scale=[0,3,5,7,10]),
    s(dict(param="Chord default",    expect="Track plays C major chord (no per-step lock)"),
      pitches=[60,64,67]),
 ]]},
 3: {"name": "MODES / ROUTING", "patterns": [[
    s(dict(param="Track Mode = CC + encoder", expect="Mode=CC; enc0 -> CC#74, value ~64"),
      sp={0x154:(1,"u8"), 0x155:(64,"u8"), 0x16a:(74,"u8"), 0x16b:(1,"u8")}),
    s(dict(param="Track Mode = FX", expect="Mode = FX"),                           sp={0x154:(2,"u8")}),
    s(dict(param="Internal routing", expect="Routed internally to track 3"),       sp={0x297:(0x0004,"u16")}),
    s(dict(param="Mute",            expect="Track is MUTED"),                      mute=True),
    s(dict(param="MIDI channel",    expect="Output channel = 5"),                  mask=(1<<4)),
    s(dict(param="Track Mode = Note (control)", expect="Mode = Note (default)")),
 ]]},
 4: {"name": "GLOBAL / RANDOM", "patterns": [[
    s(dict(param="Track Length",    expect="Loop length = 2 bars"),               length=1),
    s(dict(param="Rate",            expect="Rate = 1/8"),                          sp={0x141:(48,"u16")}),
    s(dict(param="Random intensity",expect="Random intensity = 8/16"),            sp={0x140:(64,"u8")}),
    s(dict(param="Random amount+lock (velocity)", expect="Velocity random amount ~ +12, locked"),
      sp={0x8d:(12,"s8"), 0x8f:(1,"u8")}),
    s(dict(param="Retrigger (per-step)", expect="Steps 3 & 4 retrigger (subdivide)"),
      gate=[0,2,4,6], retrig=[2,3]),
    s(dict(param="Track selection cursor", expect="Pattern opens with track 3 selected",
           caveat="this is the SINGLE-cursor form (one track selected). Multi-track selection set "
                  "is exercised separately in Bank 5."),
      note="bank-level: track_cursor=2"),
 ]]},
 5: {"name": "EXTENDED LOCKS / CYCLES", "patterns": [[
    # T1 — Accent per-step lock (id 0x18, bipolar s32). Default accent 0; step 5 = −12.
    s(dict(param="Accent per-step lock (id 0x18)",
           expect="Track plays mid-velocity; step 5 sounds quieter (accent −12 vs 0 default)",
           caveat="bipolar s32 storage just added to the builder this round — first hw test of the "
                  "encoding direction. The track-level Accent byte is left at 0 (default) so the "
                  "per-step lock is the only thing shifting the dynamic."),
      groove_locks={4: {"accent": -12}}),
    # T2 — Range per-step lock (id 0x0c, bipolar s32).
    s(dict(param="Range per-step lock (id 0x0c)",
           expect="Track default Range 0; step 5 pitch-variation set to −12 (cooler/tighter)",
           caveat="bipolar s32 storage. Range only manifests as audible pitch variance once Random "
                  "Rate is non-zero; if static, look for the value reading back on the device UI."),
      groove_locks={4: {"range": -12}}),
    # T3 — CC per-step lock (id 0x80, u8 0-127). Track in CC mode, encoder 0 = CC#74 default 64.
    s(dict(param="CC per-step lock (id 0x80)",
           expect="Track in CC mode (CC#74, default 64); step 5 sends CC value 100",
           caveat="lock id 0x80 confirmed (FORMAT_DECODE B23 P3); per-step value scale is LED-"
                  "quantized (0/64/127 observed). First write-direction test."),
      sp={0x154:(1,"u8"), 0x155:(64,"u8"), 0x16a:(74,"u8"), 0x16b:(1,"u8")},
      groove_locks={4: {"cc": 100}}),
    # T4 — per-step pitch CHORD lock (multi-note pitch lock on a single step).
    # gate active only at step 5 + lock its pitch → "fully pitch-locked" rule satisfied for pc=1.
    s(dict(param="Per-step pitch CHORD lock",
           expect="Single pulse at step 5 plays a C major chord (C/E/G), not just C"),
      gate=[4], pitches=[60], pitch_locks={4: [60, 64, 67]}),
    # T5 — per-cycle TRACK-pitch override. Track default pitch C, cycle 1 overrides to E.
    s(dict(param="Per-cycle TRACK-pitch override",
           expect="Cycle 0 plays C, cycle 1 plays E (track pitch overridden mid-loop)"),
      cycles=2, pitches=[60], cycle_pitch=[(1, [64])]),
    # T6 — per-cycle TRACK-param override. Track default steps=16, cycle 1 sets steps=8.
    # A param override is ALWAYS paired with a step-seq gate record for the SAME cycle on real
    # device backups (e.g. samples/16 blk 6 = this exact test: cycle 1, steps=8). So cycle 1 gets
    # a gate record (pulses 1 & 5, both inside the 8-step loop) alongside the steps=8 override —
    # without it the structure never occurs in device data and the bank would likely be rejected.
    s(dict(param="Per-cycle TRACK-param override (Steps)",
           expect="Cycle 0 uses 16 steps, cycle 1 only 8 steps (so cycle 1's loop is half length)",
           caveat="param-id for cycle override of Steps = 0x00 (FORMAT.md per-cycle table). First "
                  "write-direction test of cycle_params; modeled on device sample samples/16 blk 6."),
      cycles=2, steps=16, gate=[0, 4], pitches=[60],
      cycle_records=[(1, [0, 4], {}, {})], cycle_params=[(1, [(0x00, 8)])]),
 ]]},
}

# bank-level globals (tempo per bank summary; quantize + selection cursor per pattern).
# `track_cursors` per pattern is either an int (single-cursor form) or a list[int] (multi-track
# selection SET in selection/cursor order — the extended trailer form decoded in FORMAT_DECODE B23).
BANK_GLOBALS = {
    4: dict(tempo=132, pattern_quantize=[3], track_cursors=[2],
            check=dict(param="Tempo / Quantize", expect="Tempo = 132 BPM; Quantize enum=3")),
    5: dict(track_cursors=[[0, 2, 4]],
            check=dict(param="Multi-track selection set",
                       expect="Bank 5 opens with tracks 1, 3, 5 all selected at once "
                              "(not just one cursor)")),
}


def assemble_bank(bank_id, info):
    patterns_specs = info["patterns"]
    patterns_blocks = []
    for pspec in patterns_specs:
        n = len(pspec)
        blocks = []
        for i, spec in enumerate(pspec):
            # end-marker = (next track's 1-based slot) - 1; contiguous => i+1. Last track = sentinel 1.
            # (Earlier this was i+2 — an off-by-one that left slot 2 empty, shifted every later track
            # +1, and pushed Bank 0's 16th track to the out-of-range slot 17 so the device rejected it.)
            spec["end_mark"] = (i + 1) if i < n - 1 else 1
            blocks.append(make_block(spec))
        patterns_blocks.append(blocks)
    g = BANK_GLOBALS.get(bank_id, {})
    bank = M.build_bank(patterns_blocks,
                        tempo=g.get("tempo", 120),
                        pattern_quantize=g.get("pattern_quantize"),
                        track_cursors=g.get("track_cursors"))
    # post-assembly header-adjacent patches (mute @ run-0x0d, harmony value @ run-0x10)
    bank = bytearray(bank)
    runs = F.find_runs(bytes(bank))
    # map serialized block index -> spec (single pattern per bank here)
    flat = [sp for p in patterns_specs for sp in p]
    for idx, spec in enumerate(flat):
        if idx >= len(runs):
            break  # custom-scale block invisible to find_runs; handled below
        r = runs[idx]
        if spec.get("mute"):
            bank[r - 0x0d] = 1
        if "harmony" in spec:
            bank[r - 0x10] = spec["harmony"] & 0xFF
    return bytes(bank)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    round_n = _next_round()
    empty = zipfile.ZipFile(BASE_BACKUP).read("./0.t1")
    settings = zipfile.ZipFile(BASE_BACKUP).read("./Settings.json")
    wifi = zipfile.ZipFile(BASE_BACKUP).read("./Wifi.json")

    bank_bytes = {}
    for b in range(8):
        if b in BANKS:
            bank_bytes[b] = assemble_bank(b, BANKS[b])
        else:
            bank_bytes[b] = empty

    # write per-bank .t1 (handy for re-parsing) + the full backup zip
    for b in range(8):
        open(os.path.join(OUTDIR, f"{b}.t1"), "wb").write(bank_bytes[b])
    out_zip = os.path.join(OUTDIR, f"verify_findings_{round_n}.zip")
    names = ["./"] + [f"./{b}.t1" for b in range(8)] + ["./Settings.json", "./Wifi.json"]
    DT = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_STORED) as z:
        for n in names:
            zi = zipfile.ZipInfo(n, date_time=DT); zi.compress_type = zipfile.ZIP_STORED
            if n == "./":
                zi.external_attr = (0o40755 << 16) | 0x10; z.writestr(zi, b"")
            else:
                zi.external_attr = 0o644 << 16
                data = (settings if n.endswith("Settings.json") else
                        wifi if n.endswith("Wifi.json") else
                        bank_bytes[int(n[2:-3])])
                z.writestr(zi, data)
    print(f"wrote {out_zip}")
    write_check_md(round_n)
    verify(bank_bytes)


# findings located in FORMAT_DECODE.md that this backup does NOT directly exercise (write
# direction is impractical or the builder can't author them) — listed so the sheet is honest.
NOT_EXERCISED = [
    "Random **slew** (`value+0x13`) and **phase** (rotation of the 16-byte mod sequence) — need a "
    "live modulation sequence to be observable; verify by ear/behaviour, not a static read.",
    "Random **amount/lock** for params other than Velocity (one slot per param; only Velocity is set).",
    "**Timing per-step lock** — lock id unknown (FORMAT.md \"Per-step Timing/Delay lock\": device "
    "wouldn't let the owner enter one; may not exist as a per-step lock at all). NOT authored.",
]


def write_check_md(round_n):
    total = sum(len(p) for b in BANKS for p in BANKS[b]["patterns"])
    lines = [
        f"# T-1 findings verification — CHECK sheet (round {round_n})", "",
        f"Auto-generated by `decode/make_verify_backup.py` ({total} per-track tests across "
        f"{len(BANKS)} banks). Regenerate with `python3 decode/make_verify_backup.py`.", "",
        "## What this is",
        "The decode campaign located every field in the **read** direction (device → bytes). This",
        "backup tests the **write** direction: we authored each field ourselves to a chosen value and",
        f"ask the device to honour it. Restore `verify_findings_{round_n}.zip` via the **Backup menu** (it is a",
        "full 8-bank backup; banks 6–7 are empty), then walk each bank/track and tick what matches.", "",
        "## Reading conventions",
        "- Banks map to device parameter pages. **Mid/readable** values (not pegged).",
        "- **Bipolar** params: centre = 0, range −20…+20, so **+12** sits ~3/4 toward the right end.",
        "- **Counts / enums** are exact. **Velocity** is 1:1 (0–127). Sustain byte 64 = one division.",
        "- ⚠️ in a row = a caveat/low-confidence finding; read the note before judging a fail.", "",
    ]
    for b in sorted(BANKS):
        info = BANKS[b]
        lines.append(f"## Bank {b} — {info['name']}")
        g = BANK_GLOBALS.get(b)
        if g:
            lines.append(f"_Bank-level:_ {g['check']['expect']}")
        lines.append("")
        lines.append("| ✓ | Track | Parameter | Expected on device | Notes / caveats |")
        lines.append("|---|---|---|---|---|")
        flat = [sp for p in info["patterns"] for sp in p]
        for i, spec in enumerate(flat, 1):
            c = spec["check"]
            note = c.get("caveat", spec.get("note", ""))
            flag = "⚠️ " if "caveat" in c else ""
            lines.append(f"| ☐ | T{i} | {flag}{c['param']} | {c['expect']} | {note} |")
        lines.append("")
    lines += ["## Findings NOT directly exercised here", ""]
    lines += [f"- {x}" for x in NOT_EXERCISED]
    lines += ["", "## Round history", "",
              "**Round 1** (`verify_findings.zip` → CHECK1.md). Bug found: `end_mark` builder used `(i+2) if i<n-1` — left slot 2 empty and shifted every later track by +1. Symptoms: banks 2/3/4 loaded but with the slot shift; **Bank 0 (16 tracks)** was rejected because the shift pushed T16 to out-of-range slot 17.",
              "",
              "**Round 2** (`verify_findings_2.zip` → CHECK2.md). End-marker fix shipped (`next_slot − 1` per format rule); banks 0, 2, 3, 4 loaded with tracks on the named slots. **Bank 1 still didn't load.** Initial hypothesis (lock-summary + positional gap) was wrong — the gap was already gone in round 2.",
              "",
              "**Round 3** (`verify_findings_3.zip` → CHECK3.md). True bug found: Bank 1 T4 wrote `timing_sub=1` to `steps+0x146`, but the 3-point enum's only valid values are **{3, 4, 5}** (`/4=3`, `/1=4` default, `/2=5`) — `1` is out of range and crashed the bank's load. **Fix:** `timing_sub=5` (= /2 subdivision). All 5 banks (0–4) loaded; rounds 1–3 cover every PLAN.md per-track row that a static-byte write can exercise.",
              "",
              "**Round 4** (this file). Extends coverage to the findings rounds 1–3 could NOT author: a new **Bank 5 — EXTENDED LOCKS / CYCLES** plus a bank-level multi-track selection set. The builder gained: per-step lock IDs beyond velocity/sustain (Accent `0x18`, Range `0x0c`, CC `0x80`) with **signed-s32** lock-value storage for the bipolar IDs; multi-track selection in `build_bank` (the variable-length pattern trailer); and the per-cycle param/pitch override path is exercised write-direction for the first time. Bank 0 T6 **Time** is also re-authored to `1/8` (=48) instead of the round-3 default-collision `1/16`. Bank 5 T6's per-cycle param override is paired with a step-seq gate record for the same cycle (as on device sample `samples/16` blk 6) — the structure never occurs unpaired in device data.",
              "",
              "**To verify this round:** restore `verify_findings_{n}.zip` and check, in priority order: (1) **does Bank 5 load at all** (the new lock IDs / cycle-param structure are unproven write-direction — a reject is itself the key datum); (2) Bank 5 T1–T3 per-step locks read back on the device (Accent/Range/CC at step 5); (3) Bank 5 T4 step-5 plays a C-major chord; (4) T5 cycle 2 plays E, T6 cycle 2 is half-length (8 steps); (5) the bank opens with tracks 1/3/5 co-selected; (6) Bank 0 T6 Time now reads `1/8`.".replace("{n}", str(round_n)),
              "",
              "## Free-form notes / observations", "",
              "_(anything surprising, off-by-one readings, rejects, etc.)_", ""]
    out_md = os.path.join(OUTDIR, f"CHECK{round_n}.md")
    open(out_md, "w").write("\n".join(lines))
    print(f"wrote {out_md}")


def verify(bank_bytes):
    """Re-parse each bank and confirm a few representative field values read back as written."""
    print("\n--- readback sanity (decode_rebuild + parser) ---")
    for b in sorted(BANKS):
        path = os.path.join(OUTDIR, f"{b}.t1")
        res = R.test_file(path)
        print(res)


if __name__ == "__main__":
    main()
