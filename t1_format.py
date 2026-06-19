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
OFF_GATE = 0x0c                 # 16 bytes
OFF_LOCKS = 0x4c                # groove-lock count byte; lock region starts here
PAD_AFTER_LOCKS = 18            # fixed padding between lock lists and `steps`

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
    """Recover pitch count by matching the `0c 00 <pc> 00 00 00` block marker that
    precedes the pitch list (which precedes `00 0c 00 00 00` then `run`)."""
    for pc in range(0, 9):
        bstart = run - 0x0b - pc
        if bstart < 0:
            continue
        if data[bstart:bstart + 2] == b"\x0c\x00" and data[bstart + 2] == pc \
                and data[bstart + 3:bstart + 6] == b"\x00\x00\x00":
            return pc, bstart
    # fallback: assume 1 pitch
    return 1, run - 0x0c


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


def parse_track(data, run):
    pc, bstart = _pitch_count_and_start(data, run)
    pitches = list(data[bstart + 6:bstart + 6 + pc])
    gate = list(data[run + OFF_GATE:run + OFF_GATE + 16])
    groove_locks, pitch_locks, so = _parse_locks(data, run)
    # a block carrying any lock has a single 0x00 terminator byte after the steps region
    lock_term = 1 if (groove_locks or pitch_locks) else 0
    mask = data[so + S_MIDIMASK] | (data[so + S_MIDIMASK + 1] << 8)
    channels = [c + 1 for c in range(16) if mask & (1 << c)]
    div_ticks = data[so + S_DIVISION] | (data[so + S_DIVISION + 1] << 8)
    root = data[so + S_ROOT]
    return {
        "block_start": bstart,
        "run": run,
        "block_end": so + TAIL_AFTER_STEPS + lock_term,
        "pitch_count": pc,
        "pitches": pitches,                       # absolute, C3=60
        "gate": gate,                             # 16 x 0/1
        "active_steps": [i + 1 for i, g in enumerate(gate) if g],
        "steps": data[so],                        # loop length
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
    tracks = [parse_track(data, r) for r in runs]
    return {"path": path, "size": len(data), "version": "2.1.4",
            "tracks": tracks, "patterns": group_patterns(tracks)}


def main(argv):
    if len(argv) < 2:
        print("usage: t1_format.py FILE.t1 ..."); return 1
    for p in argv[1:]:
        bank = parse_bank(p)
        print(f"== {p}  ({bank['size']} B, {len(bank['tracks'])} track block(s)) ==")
        for i, t in enumerate(bank["tracks"]):
            print(f"  block {i:2d}: pitches={t['pitches']} steps={t['steps']} "
                  f"div={t['division_label']} root={t['root_name']} scale={t['scale_name']} "
                  f"vel={t['velocity']} sus={t['sustain']} "
                  f"ch={t['midi_channels']} pulses={t['active_steps']}")
            if t["pitch_locks"]:
                print(f"           pitch-locks: {{{', '.join(f'{s+1}:{v}' for s,v in sorted(t['pitch_locks'].items()))}}}")
            if t["groove_locks"]:
                print(f"           groove-locks: {{{', '.join(f'{s+1}:{v}' for s,v in sorted(t['groove_locks'].items()))}}}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
