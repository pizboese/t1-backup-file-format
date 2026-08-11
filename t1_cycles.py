#!/usr/bin/env python3
"""
t1_cycles.py — decode the per-track CYCLES + steps-to-64 structures in a `.t1` bank.

Cycles let each track loop through N variations (count 1-16, default 4); each cycle can
override track-level params and per-step data. Storage (see FORMAT.md "STEPS up to 64 +
CYCLES") is split across three places in the 803+-byte track block:

  1. cycle COUNT      -> steps+0x14d
  2. per-cycle TRACK-PITCH overrides -> header, after the base pitch list:
        [num:u8] then [cycle_idx:u8][pitch_count:u32 LE][pitches...]   (descending)
  3. per-cycle STEP-SEQUENCE records -> lock region, after the base lock counts:
        [num_edited_cycles:u8] then per cycle a 67-B(min) record:
            [cycle_idx:u8][64-B gate][groove_lock_list][pitch_lock_list]
        followed by a per-cycle TRACK-PARAM override section (sustain `0e <v>` confirmed).

Usage: python3 t1_cycles.py FILE.t1 [FILE2.t1 ...]
"""
import sys
from t1_format import (find_runs, parse_track, _parse_header, _pitch_count_and_start,
                        OFF_LOCKS, GATE_LEN)

GROOVE_PARAMS = {0x0a: "vel", 0x0e: "sus"}
# per-cycle TRACK-PARAM override ids (shared namespace; see FORMAT.md). value is u16 LE.
CYCLE_PARAMS = {0x00: "steps", 0x04: "division", 0x06: "scale",
                0x0a: "velocity", 0x0e: "sustain", 0x22: "root"}


def _parse_lock_list(data, p):
    """Read [groove_count + groove locks][pitch_count + pitch locks] at p; return
    (groove, pitch, next_offset)."""
    groove = {}
    gc = data[p]; p += 1
    for _ in range(gc):
        ec, step = data[p], data[p + 1]; p += 2
        for _ in range(ec):
            param, val = data[p], data[p + 1]
            groove.setdefault(step, {})[GROOVE_PARAMS.get(param, hex(param))] = val
            p += 5
    pitch = {}
    pcnt = data[p]; p += 1
    for _ in range(pcnt):
        step = data[p]; cnt = int.from_bytes(data[p + 1:p + 5], "little")
        pitch[step] = list(data[p + 5:p + 5 + cnt]); p += 5 + cnt
    return groove, pitch, p


def decode_block(data, run, block_hi):
    t = parse_track(data, run, block_hi=block_hi)
    pc, bstart, base, pitch_ov = _parse_header(data, run)
    out = {"steps": t["steps"], "cycles": t["cycles"], "step_group": t["step_group"],
           "pitch_overrides": pitch_ov, "records": []}
    # per-cycle step-sequence records sit after the base lock lists
    p = run + OFF_LOCKS
    _, _, p = _parse_lock_list(data, p)              # skip base lock lists
    num = data[p]; p += 1
    for _ in range(num):
        cyc = data[p]; p += 1
        gate = [i + 1 for i, g in enumerate(data[p:p + GATE_LEN]) if g]; p += GATE_LEN
        groove, pitch, p = _parse_lock_list(data, p)
        out["records"].append({"cycle": cyc, "gate_pulses": gate,
                               "groove_locks": groove, "pitch_locks": pitch})
    # per-cycle TRACK-PARAM override section (groove-lock format keyed by cycle, value u16)
    out["param_overrides"] = []                  # [(cycle_idx, {param: value})]
    nrec = data[p]; p += 1
    for _ in range(nrec):
        ec = data[p]; cyc = data[p + 1]; p += 2
        params = {}
        for _ in range(ec):
            pid = data[p]; val = int.from_bytes(data[p + 1:p + 3], "little"); p += 5
            params[CYCLE_PARAMS.get(pid, hex(pid))] = val
        out["param_overrides"].append((cyc, params))
    return out


def _parse_lock_list_raw(data, p):
    """Like _parse_lock_list but returns groove as {step:{param_id:value}} and pitch as
    {step:[notes]} in RAW form (param ids, u16 values), preserving rebuild fidelity."""
    groove = {}
    gc = data[p]; p += 1
    for _ in range(gc):
        ec, step = data[p], data[p + 1]; p += 2
        d = {}
        for _ in range(ec):
            # Value is signed int32 LE (5 bytes total incl. pid). Bipolar lock IDs (Accent 0x18,
            # Range 0x0c, perhaps Timing TBD) store negative values sign-extended; unipolar IDs
            # (vel/sustain/CC) sit in 0..127 so signed read is a no-op for them.
            pid = data[p]; val = int.from_bytes(data[p + 1:p + 5], "little", signed=True)
            d[pid] = val; p += 5
        groove[step] = d
    pitch = {}
    pcnt = data[p]; p += 1
    for _ in range(pcnt):
        step = data[p]; cnt = int.from_bytes(data[p + 1:p + 5], "little")
        pitch[step] = list(data[p + 5:p + 5 + cnt]); p += 5 + cnt
    return groove, pitch, p


def parse_for_rebuild(data, run, block_hi):
    """Return the raw cycle structures (stored order) needed to re-synthesize a block:
    {cycle_pitch, cycle_records, cycle_params} as build_track_block expects them."""
    from t1_format import _parse_header
    _, _, _, pitch_ov = _parse_header(data, run)
    p = run + OFF_LOCKS
    _, _, p = _parse_lock_list_raw(data, p)          # skip base lock lists
    num = data[p]; p += 1
    records = []
    for _ in range(num):
        cyc = data[p]; p += 1
        gate = list(data[p:p + GATE_LEN]); p += GATE_LEN
        groove, pitch, p = _parse_lock_list_raw(data, p)
        records.append((cyc, gate, groove, pitch))
    params = []
    nrec = data[p]; p += 1
    for _ in range(nrec):
        ec = data[p]; cyc = data[p + 1]; p += 2
        entries = []
        for _ in range(ec):
            pid = data[p]; val = int.from_bytes(data[p + 1:p + 3], "little"); p += 5
            entries.append((pid, val))
        params.append((cyc, entries))
    return {"cycle_pitch": pitch_ov, "cycle_records": records, "cycle_params": params}


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 1
    for path in argv[1:]:
        data = open(path, "rb").read()
        runs = find_runs(data)
        starts = [_pitch_count_and_start(data, r)[1] for r in runs]
        his = starts[1:] + [len(data)]
        print(f"== {path} ({len(runs)} blocks) ==")
        for i, (r, h) in enumerate(zip(runs, his)):
            d = decode_block(data, r, h)
            extra = []
            if d["steps"] != 16: extra.append(f"steps={d['steps']}")
            if d["cycles"] != 4: extra.append(f"cycles={d['cycles']}")
            if d["step_group"]: extra.append(f"page={d['step_group']+1}/4")
            tag = (" " + " ".join(extra)) if extra else ""
            print(f"  block {i:2d}:{tag}")
            for c, ps in d["pitch_overrides"]:
                print(f"     cycle {c+1} track-pitch -> {ps}")
            for c, params in d.get("param_overrides", []):
                print(f"     cycle {c+1} track-param -> {params}")
            for rec in d["records"]:
                bits = [f"gate={rec['gate_pulses']}"] if rec["gate_pulses"] != [1] else []
                if rec["groove_locks"]:
                    bits.append("groove=" + str({s + 1: v for s, v in rec["groove_locks"].items()}))
                if rec["pitch_locks"]:
                    bits.append("pitch=" + str({s + 1: v for s, v in rec["pitch_locks"].items()}))
                print(f"     cycle {rec['cycle']+1} step-seq: " + (", ".join(bits) if bits else "(gate=default)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
