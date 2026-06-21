#!/usr/bin/env python3
"""
make_cycle_hwtest.py — synthesize a device-loadable backup that exercises the steps-64 +
CYCLES decode from scratch (NOT self-templated), then splice it into a real backup so it can
be restored on the T-1 for hardware verification.

Two patterns, increasing in complexity track-to-track:
  Pattern 1 — step counts, cycle counts, simple per-cycle TRACK edits.
  Pattern 2 — per-cycle edits combined with per-step (gate / pitch / groove) edits.

Output: hwtest/cycle_hwtest.t1 (bank) + hwtest/project_cycle_hwtest.zip (loadable backup,
bank in slot 0). Verify the bank with:  python3 t1_cycles.py hwtest/cycle_hwtest.t1
"""
import os
import zipfile

import midi_to_t1 as M

C3, D3, E3, G3 = 60, 62, 64, 67
PID_STEPS, PID_DIV, PID_SCALE, PID_VEL, PID_SUS, PID_ROOT = 0x00, 0x04, 0x06, 0x0a, 0x0e, 0x22
DIV16 = M.DIVISIONS[16]


def pulses(*steps, length=64):
    g = [0] * length
    for s in steps:
        g[s - 1] = 1            # 1-based step -> 0-based gate index
    return g


def track(template, *, ch, steps=16, cycles=4, base_pulses=(1,), pitch=C3,
          velocity=100, sustain=64, cycle_edits=None, end_mark=1):
    """High-level track spec -> build_track_block kwargs. `cycle_edits` maps cycle_idx(0-based)
    to a dict that may contain: 'pitch'(track-pitch list), 'params'({pid:value}),
    'gate'(1-based pulse list), 'pitch_locks'({step0:[notes]}), 'groove_locks'({step0:{pid:v}})."""
    cycle_edits = cycle_edits or {}
    base_gate = pulses(*base_pulses, length=64)
    edited = sorted(cycle_edits, reverse=True)                    # device stores descending
    cycle_pitch = [(c, cycle_edits[c]["pitch"]) for c in edited if "pitch" in cycle_edits[c]]
    cycle_params = [(c, list(cycle_edits[c]["params"].items()))
                    for c in edited if "params" in cycle_edits[c]]
    cycle_records = []
    for c in edited:                                             # every edited cycle gets a record
        e = cycle_edits[c]
        g = pulses(*e["gate"], length=64) if "gate" in e else list(base_gate)
        cycle_records.append((c, g, e.get("groove_locks", {}), e.get("pitch_locks", {})))
    return M.build_track_block(
        template, gate=base_gate, pitches=[pitch], steps=steps, division=DIV16, scale=0, root=0,
        velocity=velocity, sustain=sustain, mask=1 << (ch - 1), pitch_locks={}, groove_locks={},
        cycles=cycles, step_group=0, cycle_pitch=cycle_pitch, cycle_records=cycle_records,
        cycle_params=cycle_params, end_mark=end_mark)


def build():
    tmpl = M.load_template(M.DEFAULT_TEMPLATE)

    # ── Pattern 1: steps + cycle counts + simple per-cycle TRACK-param edits ───────────
    p1_specs = [
        dict(ch=1, steps=16, cycles=4, base_pulses=(1,)),                       # baseline
        dict(ch=2, steps=32, cycles=4, base_pulses=(1, 17)),                    # 2 pages
        dict(ch=3, steps=64, cycles=4, base_pulses=(1, 33)),                    # full 64 steps
        dict(ch=4, steps=16, cycles=8, base_pulses=(1,)),                       # cycle count 8
        dict(ch=5, steps=16, cycles=4, base_pulses=(1,),
             cycle_edits={1: {"pitch": [D3]}}),                                 # cyc2 track-pitch D3
        dict(ch=6, steps=16, cycles=4, base_pulses=(1,),
             cycle_edits={2: {"params": {PID_SUS: 127}}}),                      # cyc3 sustain 16/16
    ]
    # ── Pattern 2: per-cycle + per-step edits, rising complexity ──────────────────────
    p2_specs = [
        dict(ch=1, steps=16, cycles=4, base_pulses=(1,),
             cycle_edits={0: {"pitch": [C3, E3, G3]}}),                         # cyc1 track CHORD
        dict(ch=2, steps=16, cycles=4, base_pulses=(1,),
             cycle_edits={1: {"gate": [1, 5], "pitch_locks": {0: [C3, E3, G3]}}}),  # cyc2 +pulse5 + step1 chord
        dict(ch=3, steps=16, cycles=8, base_pulses=(1,),
             cycle_edits={3: {"params": {PID_STEPS: 8}}, 7: {"pitch": [D3]}}),  # cyc4 steps8 + cyc8 pitch
        dict(ch=4, steps=16, cycles=4, base_pulses=(1,),
             cycle_edits={1: {"groove_locks": {0: {PID_VEL: 127, PID_SUS: 127}}}}),  # cyc2 step1 vel/sus 16/16
        dict(ch=5, steps=32, cycles=4, base_pulses=(1, 17),
             cycle_edits={2: {"gate": [1, 9, 17, 25], "pitch_locks": {8: [D3]}}}),   # cyc3 4 pulses + step9 D3
        dict(ch=6, steps=16, cycles=16, base_pulses=(1,),
             cycle_edits={15: {"pitch": [C3, E3, G3], "params": {PID_STEPS: 8},
                               "gate": [1, 5], "pitch_locks": {4: [D3]}}}),     # cyc16 chord+steps8+pulse5+step5 D3
    ]

    patterns = []
    for specs in (p1_specs, p2_specs):
        n = len(specs)
        blocks = [track(tmpl, end_mark=(1 if i == n - 1 else i + 1), **s)
                  for i, s in enumerate(specs)]
        patterns.append(blocks)
    # final block (P2 track6) carries cycle locks -> final_has_locks for the Form-X/Y terminator
    bank = M.build_bank(patterns, current_pattern=0, final_has_locks=True)
    return bank


def splice_zip(bank_bytes, src_zip, out_zip, slot=0):
    """Replace slot `slot` of a real backup with our bank, keeping every other entry
    byte-identical (ZIP_STORED, ./-prefixed, 11-entry order)."""
    src = zipfile.ZipFile(src_zip)
    names = ["./", "./0.t1", "./1.t1", "./2.t1", "./3.t1", "./4.t1", "./5.t1", "./6.t1",
             "./7.t1", "./Settings.json", "./Wifi.json"]
    DT = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_STORED) as z:
        for n in names:
            zi = zipfile.ZipInfo(n, date_time=DT); zi.compress_type = zipfile.ZIP_STORED
            if n == "./":
                zi.external_attr = (0o40755 << 16) | 0x10; z.writestr(zi, b""); continue
            data = bank_bytes if n == f"./{slot}.t1" else src.read(n)
            zi.external_attr = 0o644 << 16; z.writestr(zi, data)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    bank = build()
    bank_path = os.path.join(here, "hwtest", "cycle_hwtest.t1")
    open(bank_path, "wb").write(bank)
    src = os.path.join(here, "hwtest", "fromT1", "original_backup.zip")
    out = os.path.join(here, "hwtest", "project_cycle_hwtest.zip")
    splice_zip(bank, src, out, slot=0)
    print(f"wrote {bank_path}  ({len(bank)} B)")
    print(f"wrote {out}  (bank spliced into slot 0)")
