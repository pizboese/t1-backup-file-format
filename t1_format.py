#!/usr/bin/env python3
"""
t1_format.py — parser for Torso T-1 per-bank `.t1` backup files (firmware 2.1.4).

Decodes the bank into patterns -> tracks -> fields. See FORMAT.md for the byte map.
Parsing is landmark-based: each 803-ish byte track block contains the sequence
`00 01 02 ... 0b` (call its offset `run`); post-pitch fields sit at fixed offsets from
`run`, so they are independent of the variable-length pitch list.
"""
import sys

RUN = bytes(range(0, 12))                 # 00 01 .. 0b  block landmark
SCALES = ["Chromatic", "Major", "Minor", "Penta", "Hira", "Iwato", "Tetra"]
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# offsets relative to `run` (stable: before the per-step lock region)
OFF_GATE = 0x0c                 # GATE array start. The array is a FIXED 64 bytes (steps 1-64),
GATE_LEN = 64                   #   one byte/step (01=pulse); OFF_LOCKS sits right after it.
OFF_LOCKS = 0x4c                # groove-lock count byte; lock region starts here (= OFF_GATE+64)
PAD_AFTER_LOCKS = 18            # fixed padding between lock lists and `steps`

# steps-region offsets for the cycles feature (see FORMAT.md "STEPS up to 64 + CYCLES")
S_CYCLES = 0x14d    # cycle count (1-16, default 4)
S_STEPGROUP = 0x2b0 # step-group page selector (UI cursor): 0=1-16 1=17-32 2=33-48 3=49-64

# offsets relative to the `steps` field (which is pushed later by the lock region)
S_DIVISION = 0x2a   # u16 LE: ticks/step @96 PPQN (value*divisor = 384)
S_SCALE = 0x40
S_VELOCITY = 0x7b
S_SUSTAIN = 0xa5
S_MIDIMASK = 0xe4   # u16 LE
S_ROOT = 0x13f
TAIL_AFTER_STEPS = 0x2b7        # steps .. block end (fixed per-step region)

GROOVE_PARAMS = {0x0a: "velocity", 0x0e: "sustain"}
PPQN = 96                       # T-1 internal: quarter note = 96 ticks


def find_runs(data):
    out, i = [], 0
    while True:
        j = data.find(RUN, i)
        if j < 0:
            break
        out.append(j)
        i = j + 1
    return out


def _pitch_count_and_start(data, run):
    """Recover pitch count + block start by matching the `0c 00 <pc> 00 00 00` block marker
    that precedes the pitch list. The marker is normally `0x0b + pc` bytes before `run`, but
    per-cycle TRACK-PITCH overrides (FORMAT.md) insert extra bytes between the pitch list and
    `run`, so scan backward for the nearest valid marker instead of assuming a fixed gap."""
    for back in range(0x0b, 0x60):
        bstart = run - back
        if bstart < 0:
            break
        if data[bstart:bstart + 2] == b"\x0c\x00" \
                and data[bstart + 3:bstart + 6] == b"\x00\x00\x00":
            pc = data[bstart + 2]
            if pc <= 8 and bstart + 6 + pc <= run:
                return pc, bstart
    # fallback: assume 1 pitch
    return 1, run - 0x0c


def _parse_header(data, run):
    """Parse the block header (back from `run`): locate the `0c 00 <pc> 00 00 00` marker,
    read the base pitch list, then any per-cycle TRACK-PITCH overrides that follow it.
    Returns (pitch_count, block_start, base_pitches, pitch_overrides) where pitch_overrides
    is a list of (cycle_idx, [pitches]). See FORMAT.md "Per-cycle TRACK-PITCH overrides"."""
    pc, bstart = _pitch_count_and_start(data, run)
    base = list(data[bstart + 6:bstart + 6 + pc])
    p = bstart + 6 + pc
    overrides = []
    num_ov = data[p]
    # validate: the override list is immediately followed by the `0c 00 00 00`->run separator
    q = p + 1
    ok = True
    for _ in range(num_ov):
        cyc = data[q]; cnt = int.from_bytes(data[q + 1:q + 5], "little")
        if cnt > 8 or q + 5 + cnt > run:
            ok = False; break
        overrides.append((cyc, list(data[q + 5:q + 5 + cnt])))
        q += 5 + cnt
    if not ok:
        overrides = []
    return pc, bstart, base, overrides


def _last_zoneB_term(data, run, hi):
    """Locate the Zone-B `00 00 00 53 00` terminator (at steps+0x295). Robust anchor for
    `steps` on blocks whose lock region carries per-cycle records (which shift `steps`)."""
    last = -1
    for j in range(run, hi - 1):
        if data[j] == 0x53 and data[j - 3:j] == b"\x00\x00\x00" and data[j + 1] == 0:
            last = j
    return last


def _parse_locks(data, run):
    """Parse the per-step lock region (groove list then pitch list). Returns
    (groove_locks, pitch_locks, steps_offset)."""
    p = run + OFF_LOCKS
    groove_count = data[p]; p += 1
    groove = {}                                   # step(0-based) -> {param: value}
    for _ in range(groove_count):
        entry_count, step = data[p], data[p + 1]
        p += 2
        for _ in range(entry_count):              # one [param value 00 00 00] per locked param
            param, val = data[p], data[p + 1]
            groove.setdefault(step, {})[GROOVE_PARAMS.get(param, param)] = val
            p += 5
    pitch_count = data[p]; p += 1
    pitch = {}                                     # step(0-based) -> [pitches]
    for _ in range(pitch_count):
        step = data[p]
        cnt = int.from_bytes(data[p + 1:p + 5], "little")
        pitch[step] = list(data[p + 5:p + 5 + cnt])
        p += 5 + cnt
    steps_offset = p + PAD_AFTER_LOCKS
    return groove, pitch, steps_offset


def parse_track(data, run, block_hi=None):
    pc, bstart, pitches, pitch_overrides = _parse_header(data, run)
    gate = list(data[run + OFF_GATE:run + OFF_GATE + GATE_LEN])    # full 64-step gate
    groove_locks, pitch_locks, so = _parse_locks(data, run)
    # Per-cycle step-sequence records (FORMAT.md) live between the base lock lists and `steps`,
    # shifting `steps` later. Detect them (num_edited_cycles byte) and, when present, relocate
    # `steps` via the Zone-B `53` terminator (steps+0x295) which is cycle/lock-independent.
    # num_edited_cycles sits immediately AFTER the (variable-length) base lock lists — i.e. at
    # the position _parse_locks walked to before adding the 18-byte pad (so - PAD_AFTER_LOCKS).
    # Reading it at a fixed run+0x4e offset only works when the base track is lock-free; a base
    # block that itself carries locks would misread a mid-list byte. (so is relocated below.)
    num_edited_cycles = data[so - PAD_AFTER_LOCKS]
    has_cycle_records = num_edited_cycles > 0 or bool(pitch_overrides)
    if has_cycle_records and block_hi is not None:
        term = _last_zoneB_term(data, run, block_hi)
        if term > 0:
            so = term - 0x295
    # A block carrying any lock has a single terminator byte after the steps region. Locks may
    # live in the base track OR in a per-cycle record; the device sets the lock-summary flag
    # (steps+0x29c) whenever ANY are present, so use it to detect cycle-only lock blocks too.
    lock_term = 1 if (groove_locks or pitch_locks or data[so + 0x29c]) else 0
    mask = data[so + S_MIDIMASK] | (data[so + S_MIDIMASK + 1] << 8)
    channels = [c + 1 for c in range(16) if mask & (1 << c)]
    div_ticks = data[so + S_DIVISION] | (data[so + S_DIVISION + 1] << 8)
    root = data[so + S_ROOT]
    return {
        "block_start": bstart,
        "run": run,
        "block_end": so + TAIL_AFTER_STEPS + lock_term,
        "pitch_count": pc,
        "pitches": pitches,                       # absolute, C3=60 (base / current cycle)
        "gate": gate,                             # 64 x 0/1 (full step range)
        "active_steps": [i + 1 for i, g in enumerate(gate) if g],
        "steps": data[so],                        # loop length (1-64)
        "cycles": data[so + S_CYCLES],            # cycle count (1-16, default 4)
        "step_group": data[so + S_STEPGROUP],     # page selector 0-3 (UI cursor)
        "pitch_overrides": pitch_overrides,       # per-cycle track pitch: [(cycle_idx,[pitches])]
        "num_edited_cycles": num_edited_cycles,   # # of cycles with stored step-seq overrides
        "division_ticks": div_ticks,              # ticks/step @96 PPQN
        "division_label": f"/{384 // div_ticks}" if div_ticks else "?",
        "scale": data[so + S_SCALE],
        "scale_name": SCALES[data[so + S_SCALE]] if data[so + S_SCALE] < len(SCALES) else "?",
        "root": root,
        "root_name": NOTE_NAMES[root] if root < 12 else "?",
        "velocity": data[so + S_VELOCITY],
        "sustain": data[so + S_SUSTAIN],
        "midi_mask": mask,
        "midi_channels": channels,
        "pitch_locks": pitch_locks,               # step(0-based) -> [pitches]
        "groove_locks": groove_locks,             # step(0-based) -> {param: value}
    }


def group_patterns(tracks):
    """Group flat track blocks into patterns by detecting the 12-byte gap that separates
    patterns (tracks within a pattern are contiguous)."""
    patterns, cur = [], []
    for i, t in enumerate(tracks):
        if cur:
            gap = t["block_start"] - tracks[i - 1]["block_end"]
            if gap >= 8:           # pattern boundary (8B trailer + 4B header)
                patterns.append(cur); cur = []
        cur.append(t)
    if cur:
        patterns.append(cur)
    return patterns


def parse_bank(path):
    data = open(path, "rb").read()
    if data[:6] != b"\x052.1.4":
        raise ValueError(f"{path}: not a 2.1.4 .t1 file (got {data[:6]!r})")
    runs = find_runs(data)
    # pass each block's upper bound (next block start) so cycle-bearing blocks can anchor
    # `steps` off the Zone-B terminator instead of the (shifted) forward lock walk.
    starts = [_pitch_count_and_start(data, r)[1] for r in runs]
    his = starts[1:] + [len(data)]
    tracks = [parse_track(data, r, block_hi=h) for r, h in zip(runs, his)]
    return {"path": path, "size": len(data), "version": "2.1.4",
            "tracks": tracks, "patterns": group_patterns(tracks)}


def main(argv):
    if len(argv) < 2:
        print("usage: t1_format.py FILE.t1 ..."); return 1
    for p in argv[1:]:
        bank = parse_bank(p)
        print(f"== {p}  ({bank['size']} B, {len(bank['tracks'])} track block(s)) ==")
        for i, t in enumerate(bank["tracks"]):
            cyc = f" cycles={t['cycles']}" if t['cycles'] != 4 else ""
            grp = f" page={t['step_group']+1}/4" if t['step_group'] else ""
            print(f"  block {i:2d}: pitches={t['pitches']} steps={t['steps']}{cyc}{grp} "
                  f"div={t['division_label']} root={t['root_name']} scale={t['scale_name']} "
                  f"vel={t['velocity']} sus={t['sustain']} "
                  f"ch={t['midi_channels']} pulses={t['active_steps']}")
            if t["pitch_overrides"]:
                print(f"           cycle-pitch: {{{', '.join(f'cyc{c+1}:{v}' for c,v in t['pitch_overrides'])}}}"
                      + (f"  (+{t['num_edited_cycles']} edited-cycle step-seq record(s))" if t['num_edited_cycles'] else ""))
            elif t["num_edited_cycles"]:
                print(f"           edited-cycle step-seq records: {t['num_edited_cycles']}")
            if t["pitch_locks"]:
                print(f"           pitch-locks: {{{', '.join(f'{s+1}:{v}' for s,v in sorted(t['pitch_locks'].items()))}}}")
            if t["groove_locks"]:
                print(f"           groove-locks: {{{', '.join(f'{s+1}:{v}' for s,v in sorted(t['groove_locks'].items()))}}}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
