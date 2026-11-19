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

# tail of the steps-region: per-block lock-summary + position end-marker (see FORMAT.md
# "TRUE chord blocker" / track positions). The end-marker encodes the NEXT serialized track's
# position minus 1 (last track of a pattern = 1); empty tracks between are skipped, not stored.
S_LOCK_FLAG = 0x29c   # 0 = plain block; !=0 = "summary" form (has locks OR a positional gap)
S_LOCK_CURSOR = 0x2a0 # u16: last-edited lock step (lock blocks) OR #empty tracks skipped (gap)
S_END_2B5 = 0x2b5     # end-marker on a PLAIN block (summary block: 0)
S_END_2B6 = 0x2b6     # end-marker on a SUMMARY block (plain block: 0)

# offsets relative to the `steps` field (which is pushed later by the lock region)
S_DIVISION = 0x2a   # u16 LE: ticks/step @96 PPQN (value*divisor = 384)
S_SCALE = 0x40
S_PROBABILITY = 0x79  # s8, center 0 (− pulses-only / + all-notes); 2 B before velocity (backup-1)
S_VELOCITY = 0x7b
S_TIMING = 0xba     # s8, center 0: swing amount (every 2nd step earlier/later) (backup-1)
S_SUSTAIN = 0xa5
S_MIDIMASK = 0xe4   # u16 LE
S_DELAY = 0x13e     # s8, center 0: whole-track shift against the grid (backup-1)
S_ROOT = 0x13f
S_TIMING_SUB = 0x146  # timing subdivision enum (/1=4 /2=5 /4=3; default /1=4) (backup-1)
S_LENGTH = 0x14b    # track loop-length enum 0-15 (distinct from `steps`; see LENGTH_BARS) (backup-1)
S_FREEDIV = 0x299   # free-division flag: 0=fixed, 1=free (value stays the S_DIVISION u16) (backup-1)
TAIL_AFTER_STEPS = 0x2b7        # steps .. block end (fixed per-step region)

# Length enum (S_LENGTH) -> loop length in BARS (None = infinite). Default 0 = 1 bar. backup-1.
LENGTH_BARS = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: None,
               9: 0.5, 10: 0.25, 11: 0.125, 12: 0.0625, 13: 0.03125, 14: 0.015625, 15: 16}


def _s8(v):
    """Interpret a stored byte as a signed int8 (bipolar params: Timing, Delay, Probability)."""
    return v - 256 if v > 127 else v


def length_label(enum):
    bars = LENGTH_BARS.get(enum)
    if bars is None:
        return "inf"
    return f"{bars}bar" if bars >= 1 else f"1/{int(round(1 / bars))}"

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


def _parse_header(data, run, block_start=None):
    """Parse the block header: read the base pitch list, then any per-cycle TRACK-PITCH overrides
    that follow it. Returns (pitch_count, block_start, base_pitches, pitch_overrides) where
    pitch_overrides is a list of (cycle_idx, [pitches]). See FORMAT.md "Per-cycle TRACK-PITCH overrides"."""
    if block_start is None:
        pc_fallback, block_start = _pitch_count_and_start(data, run)
    pc = data[block_start + 2]
    base = list(data[block_start + 6:block_start + 6 + pc])
    p = block_start + 6 + pc
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
    return pc, block_start, base, overrides


def _skip_lock_lists(data, p):
    """Skip [groove list][pitch list] at p (the base track's, or a cycle record's). Returns end offset."""
    for _ in range(2):
        n = data[p]; p += 1
        if _ == 0:                               # groove: [entries][step] then entries x [param][val][00 00 00]
            for _ in range(n):
                p += 2 + data[p] * 5
        else:                                    # pitch: [step][count u32][pitches]
            for _ in range(n):
                p += 5 + int.from_bytes(data[p + 1:p + 5], "little")
    return p


def walk_block(data, start):
    """Walk one track block forward through its grammar from `start` (its leading u16) and return
    (block_start, run, block_end), or raise ValueError.

    A block is a sequential stream — [u16 (usually 12)] [u32 note count][notes] [pitch overrides]
    [u32 scale length][scale degrees] [64-B gate] [lock lists] [cycle records] [param overrides]
    [16-B pad] [steps region] [terminator] — with no length or offset fields, so everything is
    walked field by field. Unlike the `0c 00`-marker + `00 01..0b`-run landmark scan, this handles
    blocks with custom scales (the "run" is the scale table, not a constant) or a non-12 leading
    u16 (both occur: samples 22/23). The walk is validated against the fixed Zone-B terminator, so
    a misparse fails loudly instead of yielding a corrupt block."""
    if start + 10 > len(data):
        raise ValueError("truncated")
    note_count = int.from_bytes(data[start + 2:start + 6], "little")
    if not 1 <= note_count <= 16:
        raise ValueError(f"bad note count {note_count} at {start:#x}")
    try:
        p = start + 6 + note_count
        num_ov = data[p]; p += 1
        if num_ov > 16:
            raise ValueError("bad pitch-override count")
        for _ in range(num_ov):                  # [cycle][count u32][pitches]
            p += 5 + int.from_bytes(data[p + 1:p + 5], "little")
        scale_len = int.from_bytes(data[p:p + 4], "little")
        if not 1 <= scale_len <= 12:
            raise ValueError(f"bad scale length {scale_len} at {p:#x}")
        gate = p + 4 + scale_len
        p = _skip_lock_lists(data, gate + GATE_LEN)
        num_rec = data[p]; p += 1
        if num_rec > 16:
            raise ValueError("bad cycle-record count")
        for _ in range(num_rec):                 # [cycle][64-B gate][lock lists]
            p = _skip_lock_lists(data, p + 1 + GATE_LEN)
        num_par = data[p]; p += 1
        if num_par > 64:
            raise ValueError("bad param-override count")
        for _ in range(num_par):                 # [count][cycle] then count x [param][u16][00 00]
            p += 2 + data[p] * 5
        steps = p + 16                           # 16-B pad (PAD_AFTER_LOCKS' 18 = these 2 count bytes + 16)
    except IndexError:
        raise ValueError("truncated block") from None
    if steps + TAIL_AFTER_STEPS > len(data) or data[steps + 0x292:steps + 0x296] != b"\x00\x00\x00\x53":
        raise ValueError(f"Zone-B terminator not at steps={steps:#x} as the grammar predicts")
    summary = data[steps + S_LOCK_FLAG] != 0
    form_x = summary and data[steps + TAIL_AFTER_STEPS - 1] == 0
    end = steps + TAIL_AFTER_STEPS + (1 if summary else 0) + (1 if form_x else 0)
    return start, gate - OFF_GATE, end


def find_blocks(data, start, stop):
    """Walk consecutive blocks from `start` until `stop`. Returns [(block_start, run, block_end)];
    stops at the first block that doesn't parse (callers fall back to the landmark scan)."""
    out = []
    while start < stop:
        try:
            bs, run, end = walk_block(data, start)
        except ValueError:
            break
        out.append((bs, run, end))
        start = end
    return out


def _walkable(data, o):
    try:
        walk_block(data, o)
        return True
    except ValueError:
        return False


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


def parse_track(data, run, block_hi=None, block_start=None):
    pc, bstart, pitches, pitch_overrides = _parse_header(data, run, block_start)
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
    lock_term = 1 if (groove_locks or pitch_locks or data[so + S_LOCK_FLAG]) else 0
    # Position end-marker. Value = (next serialized track's position) - 1; the pattern's last
    # track uses a cursor sentinel (parse_bank ignores it). It sits at 0x2b6 on a SUMMARY block
    # (one carrying locks; 0x29c != 0) and at 0x2b5 on a PLAIN block. A positional gap does NOT
    # by itself force summary form — a plain block's 0x2b5 marker can jump (device-confirmed by
    # project2.zip: tracks 1,4,5,8,16, where the 5->8 and 8->16 gaps are PLAIN). parse_bank turns
    # these markers into absolute `position`s.
    summary_form = data[so + S_LOCK_FLAG] != 0
    end_marker = data[so + S_END_2B6] if summary_form else data[so + S_END_2B5]
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
        "probability": _s8(data[so + S_PROBABILITY]),  # signed; center 0 (backup-1)
        "timing": _s8(data[so + S_TIMING]),            # signed swing amount; center 0 (backup-1)
        "timing_sub": data[so + S_TIMING_SUB],         # subdivision enum (/1=4 /2=5 /4=3)
        "delay": _s8(data[so + S_DELAY]),              # signed track shift; center 0 (backup-1)
        "length": data[so + S_LENGTH],                 # loop-length enum 0-15 (distinct from steps)
        "length_bars": LENGTH_BARS.get(data[so + S_LENGTH]),  # bars (None=infinite)
        "free_division": bool(data[so + S_FREEDIV]),   # True = free (non-grid) division mode
        "midi_mask": mask,
        "midi_channels": channels,
        "pitch_locks": pitch_locks,               # step(0-based) -> [pitches]
        "groove_locks": groove_locks,             # step(0-based) -> {param: value}
        "summary_form": summary_form,             # block carries locks (marker lives at 0x2b6)
        "end_marker": end_marker,                 # raw marker = next track's position - 1 (last=cursor)
        # "position" (1-based track slot in its pattern) is filled by parse_bank.
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
    if len(data) < 10 or data[-4:] != b"os|t":
        raise ValueError(f"{path}: missing or invalid 'os|t' integrity tag")
    vlen = data[0]
    vstr = data[1:1+vlen].decode("ascii", errors="replace")
    if not (vstr.startswith("2.1.") or vstr.startswith("2.")):
        raise ValueError(f"{path}: unsupported firmware version {vstr!r} (expected 2.1.x)")
    # Block discovery, grammar-first: walk the sequential block stream (handles custom scales and
    # non-12 leading u16s, which the `00 01..0b` landmark scan misses — e.g. samples 22/23). Falls
    # back to the landmark scan when the walk can't cover the bank. An empty bank has no blocks.
    bstarts, runs, his = [], [], []
    if data[6] == 0:
        pass                                    # empty bank: no blocks to walk
    else:
        try:
            p = 0x0b                            # [npat][pslot][tc][tslot][flags] -> first block
            summary_start = len(data) - 4 - (12 if vstr <= "2.1.4" else 11)
            for i in range(data[6]):
                if i == 0:
                    slot, tc, bs = data[7], data[8], 0x0b   # pattern 0's header is the bank header itself
                else:                   # later patterns: [slot][tc] header, found past the variable trailer
                    slot, tc, bs = data[p], data[p + 1], p + 4
                if not (slot < 16 and 1 <= tc <= 16):
                    raise ValueError(f"bad pattern header at {p if i else 7:#x}")
                for _ in range(tc):             # tracks within a pattern abut exactly
                    bs, run, end = walk_block(data, bs)
                    bstarts.append(bs); runs.append(run); his.append(end)
                    bs = end
                if i < data[6] - 1:             # skip the variable-length pattern trailer
                    p = next((q for q in range(bs, summary_start)
                              if data[q] < 16 and 1 <= data[q + 1] <= 16 and data[q + 2] < 16
                              and _walkable(data, q + 4)), None)
                    if p is None:
                        raise ValueError("next pattern header not found")
            if bs > summary_start:
                raise ValueError("last pattern runs past the bank summary")  # the 8-B end-trailer may follow
        except ValueError:
            bstarts = None
            runs = find_runs(data)
            starts = [_pitch_count_and_start(data, r)[1] for r in runs]
            his = starts[1:] + [len(data)]
    # pass each block's upper bound (next block start) so cycle-bearing blocks can anchor
    # `steps` off the Zone-B terminator instead of the (shifted) forward lock walk.
    tracks = [parse_track(data, r, block_hi=h, block_start=bs)
              for r, h, bs in zip(runs, his, bstarts if bstarts is not None else [None] * len(runs))]
    patterns = group_patterns(tracks)
    # Assign each track its 1-based position within its pattern. The FIRST serialized track's slot
    # is stored explicitly: byte 0x09 for pattern 0, and the 3rd byte of each later pattern's
    # 4-byte gap header (block_start-2) — value = first_slot - 1 (device-confirmed by project3.zip:
    # a lone track on slot 8 stores 0x09=7). Each subsequent track's position = previous block's
    # end-marker + 1 (the marker = next_position - 1, so empty slots between tracks are recovered).
    # The pattern's last block's marker is a UI sentinel (selection count) and is not used.
    for pi, pat in enumerate(patterns):
        first_slot = (data[0x09] if pi == 0 else data[pat[0]["block_start"] - 2]) + 1
        pos = first_slot
        for t in pat:
            t["position"] = pos
            pos = t["end_marker"] + 1
    # Tempo (global, per-bank) = first 2 bytes of the 12-B bank summary (u16 LE BPM); the summary
    # sits in the last 16 bytes (12 + "os|t"). Per-pattern Quantize = the 4th byte of each pattern's
    # 8-B end trailer (`00 00 <cursor> <quantize> 00 00 00 00`). Both decoded in backup-1.
    # The summary is 12 B on 2.1.4 but 11 B on 2.1.5 (tempo u16 LE, then 9 zero bytes in the
    # 2.1.5 banks/autosave seen so far), so locate it from the version, not a fixed -16.
    summary = len(data) - 4 - (12 if vstr <= "2.1.4" else 11)
    tempo = data[summary] | (data[summary + 1] << 8)
    quantize = []
    for pi, pat in enumerate(patterns):
        if pi < len(patterns) - 1:
            q_off = patterns[pi + 1][0]["block_start"] - 12 + 3   # trailer 4th byte
        else:
            q_off = summary - 8 + 3                               # final trailer before summary
        quantize.append(data[q_off])
    return {"path": path, "size": len(data), "version": vstr, "tempo": tempo,
            "tracks": tracks, "patterns": patterns, "quantize": quantize}


def main(argv):
    if len(argv) < 2:
        print("usage: t1_format.py FILE.t1 ..."); return 1
    for p in argv[1:]:
        bank = parse_bank(p)
        print(f"== {p}  ({bank['size']} B, {len(bank['tracks'])} track block(s), "
              f"tempo={bank['tempo']} BPM, quantize={bank['quantize']}) ==")
        for i, t in enumerate(bank["tracks"]):
            cyc = f" cycles={t['cycles']}" if t['cycles'] != 4 else ""
            grp = f" page={t['step_group']+1}/4" if t['step_group'] else ""
            pos = f" trk#{t.get('position', '?')}"
            extra = "".join([
                f" timing={t['timing']}" if t['timing'] else "",
                f" delay={t['delay']}" if t['delay'] else "",
                f" prob={t['probability']}" if t['probability'] else "",
                f" len={length_label(t['length'])}" if t['length'] else "",
                " free-div" if t['free_division'] else "",
            ])
            print(f"  block {i:2d}:{pos} pitches={t['pitches']} steps={t['steps']}{cyc}{grp} "
                  f"div={t['division_label']} root={t['root_name']} scale={t['scale_name']} "
                  f"vel={t['velocity']} sus={t['sustain']} "
                  f"ch={t['midi_channels']} pulses={t['active_steps']}{extra}")
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
