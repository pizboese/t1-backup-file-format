#!/usr/bin/env python3
"""
make_2mid_cycles.py — ONE-OFF import of midi/2.mid onto the T-1 using CYCLES.

Special-case mapping requested for this file only (NOT a general importer rule):
  * the two SMF tracks ("Untitled 2" = chords, "Untitled 2 (Bass)" = bass) become the
    two T-1 tracks of ONE pattern (bank 0, pattern 1);
  * the file's 8 bars are distributed across the track's 8 CYCLES — bar k -> cycle k,
    each cycle a 16-step (/16) bar. Bar 0 = base cycle; bars 1-7 = per-cycle records.

Output: hwtest/2mid_cycles.t1 + midi/project_2mid_cycles.zip (bank spliced into slot 0).
Inspect with: python3 t1_cycles.py hwtest/2mid_cycles.t1
"""
import os
import struct
import zipfile

import midi_to_t1 as M

DIV = 16
STEPS = 16
NBARS = 8


def _read_vlq(d, i):
    n = 0
    while True:
        b = d[i]; i += 1
        n = (n << 7) | (b & 0x7f)
        if not (b & 0x80):
            return n, i


def read_midi_tracks_named(path):
    """Parse an SMF, split by SMF track (NOT merged by MIDI channel). Returns
    (ppqn, [(name, [(start,end,note,vel), ...]), ...]) for every track that carries notes,
    capturing the track-name meta event (0xFF 0x03)."""
    d = open(path, "rb").read()
    _, _fmt, ntrk, division = struct.unpack(">IHHH", d[4:14])
    ppqn = division
    tracks = []
    pos = 14
    for _ in range(ntrk):
        length = struct.unpack(">I", d[pos + 4:pos + 8])[0]
        i, end = pos + 8, pos + 8 + length
        t = 0; status = 0; active = {}; notes = []; name = None
        while i < end:
            dt, i = _read_vlq(d, i); t += dt
            b = d[i]
            if b & 0x80:
                status = b; i += 1
            ev = status & 0xf0
            if ev in (0x80, 0x90, 0xa0, 0xb0, 0xe0):
                d1, d2 = d[i], d[i + 1]; i += 2
                if ev == 0x90 and d2 > 0:
                    active[d1] = (t, d2)
                elif ev == 0x80 or (ev == 0x90 and d2 == 0):
                    st = active.pop(d1, None)
                    if st is not None:
                        notes.append((st[0], t, d1, st[1]))
            elif ev in (0xc0, 0xd0):
                i += 1
            elif status == 0xff:
                mtype = d[i]; i += 1
                mlen, i = _read_vlq(d, i)
                if mtype == 0x03:
                    name = d[i:i + mlen].decode("latin1")
                i += mlen
            elif status in (0xf0, 0xf7):
                slen, i = _read_vlq(d, i); i += slen
            else:
                i += 1
        if notes:
            tracks.append((name, notes))
        pos = end
    return ppqn, tracks


def quantize_bar(bar_notes, grid):
    """bar_notes = [(rel_start, rel_end, note, vel)] within one bar. Returns
    {step0: {'notes':[...], 'vel':v, 'sus':s}} on a 16-step grid."""
    per = {}
    for rs, re, note, vel in bar_notes:
        step = round(rs / grid)
        if step >= STEPS:
            continue
        slot = per.setdefault(step, {"notes": [], "vel": [], "sus": []})
        slot["notes"].append(note)
        slot["vel"].append(vel)
        steps_long = (re - rs) / grid
        slot["sus"].append(min(127, max(0, round(steps_long * 64) - 1)))
    out = {}
    for step, slot in per.items():
        out[step] = {
            "notes": sorted(set(slot["notes"])),
            "vel": M._most_common(slot["vel"], 100),
            "sus": M._most_common(slot["sus"], 63),
        }
    return out


def build_track(template, name, notes, ppqn, ch, end_mark):
    """Map one SMF track's notes -> a T-1 track block whose 8 cycles are the 8 bars."""
    grid = ppqn * 4 // DIV                 # ticks per 16-step grid step
    bar_ticks = ppqn * 4
    # bucket notes per bar, store bar-relative ticks
    bars = {b: [] for b in range(NBARS)}
    for start, end, note, vel in notes:
        b = start // bar_ticks
        if b >= NBARS:
            continue
        bars[b].append((start - b * bar_ticks, end - b * bar_ticks, note, vel))
    quant = {b: quantize_bar(bars[b], grid) for b in range(NBARS)}

    # track-level defaults across ALL bars (so per-cycle overrides stay minimal)
    all_singles, all_vel, all_sus = [], [], []
    for q in quant.values():
        for st in q.values():
            if len(st["notes"]) == 1:
                all_singles.append(st["notes"][0])
            all_vel.append(st["vel"])
            all_sus.append(st["sus"])
    if all_singles:
        default_pitch = M._most_common(all_singles, 60)
    else:
        mins = [min(st["notes"]) for q in quant.values() for st in q.values()]
        default_pitch = M._most_common(mins, 60)
    default_vel = M._most_common(all_vel, 100)
    default_sus = M._most_common(all_sus, 63)

    def bar_to_cycle(q):
        """One quantized bar -> (gate64, groove_locks, pitch_locks). Every active step is
        pitch-locked (covers chords + per-step pitch; base default never sounds)."""
        gate = [0] * 64
        pitch_locks = {}
        groove_locks = {}
        for step, st in q.items():
            gate[step] = 1
            pitch_locks[step] = st["notes"]
            gl = {}
            if st["vel"] != default_vel:
                gl[M.PARAM_VELOCITY] = st["vel"]
            if st["sus"] != default_sus:
                gl[M.PARAM_SUSTAIN] = st["sus"]
            if gl:
                groove_locks[step] = gl
        return gate, groove_locks, pitch_locks

    # ENCODING CHOICE (de-risked): keep the base track LOCK-FREE and put EVERY bar's per-step
    # data (incl. bar 0) into a per-cycle record. This mirrors the hardware-verified cycle banks
    # (make_cycle_hwtest: lock-free base + per-step locks living in cycle records, plus a verified
    # cycle-0 record), avoiding the untested "base track carries locks AND has cycle records" combo
    # (no device sample exercises it). The base gate is cosmetic (bar 0's shape) — never played,
    # since all 8 cycles are overridden by records.
    base_gate, _base_groove, _base_pitch = bar_to_cycle(quant[0])
    # bars 0..7 -> per-cycle records, stored DESCENDING by cycle index (device order)
    cycle_records = []
    for c in range(NBARS - 1, -1, -1):
        g, gr, pl = bar_to_cycle(quant[c])
        cycle_records.append((c, g, gr, pl))

    print(f"  track ch{ch} {name!r}: default_pitch={default_pitch} "
          f"vel={default_vel} sus={default_sus}")
    for b in range(NBARS):
        active = sorted(quant[b])
        if active:
            notestr = ", ".join(f"{s + 1}:{quant[b][s]['notes']}" for s in active)
            print(f"    bar{b}/cyc{b}: {notestr}")
        else:
            print(f"    bar{b}/cyc{b}: (empty)")

    return M.build_track_block(
        template, gate=base_gate, pitches=[default_pitch], steps=STEPS,
        division=M.DIVISIONS[DIV], scale=0, root=0, velocity=default_vel,
        sustain=default_sus, mask=1 << (ch - 1), pitch_locks={},
        groove_locks={}, cycles=NBARS, step_group=0, cycle_pitch=[],
        cycle_records=cycle_records, cycle_params=[], end_mark=end_mark)


def splice_zip(bank_bytes, src_zip, out_zip, slot=0):
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
    # integrity: every untouched entry byte-identical
    out = zipfile.ZipFile(out_zip)
    for n in names:
        if n in ("./", f"./{slot}.t1"):
            continue
        assert src.read(n) == out.read(n), f"{n} changed!"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    template = M.load_template(M.DEFAULT_TEMPLATE)
    ppqn, tracks = read_midi_tracks_named(os.path.join(here, "midi", "2.mid"))
    print(f"2.mid: ppqn={ppqn}, {len(tracks)} SMF track(s) with notes")

    n = len(tracks)
    blocks = []
    for i, (name, notes) in enumerate(tracks):
        end_mark = 1 if i == n - 1 else i + 1
        blocks.append(build_track(template, name, notes, ppqn, ch=1, end_mark=end_mark))

    bank = M.build_bank([blocks], current_pattern=0, final_has_locks=True)
    bank_path = os.path.join(here, "hwtest", "2mid_cycles.t1")
    open(bank_path, "wb").write(bank)
    src = os.path.join(here, "hwtest", "fromT1", "original_backup.zip")
    out = os.path.join(here, "midi", "project_2mid_cycles.zip")
    splice_zip(bank, src, out, slot=0)
    print(f"wrote {bank_path}  ({len(bank)} B)")
    print(f"wrote {out}  (bank spliced into slot 0)")


if __name__ == "__main__":
    main()
