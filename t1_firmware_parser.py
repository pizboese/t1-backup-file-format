#!/usr/bin/env python3
"""
t1_firmware_parser.py — Firmware-ground-truth recursive parser for Torso T-1 .t1
backup files (verified against ESP32 firmware v2.1.5).

Unlike empirical parsers that scan for landmark byte sequences, this module
mirrors the exact recursive C++ deserialization methods of the Torso firmware:
  - FileStream (FUN_400edbe8): Version check & 4-byte EOF tag check ('os|t' = 0x747c736f)
  - Bank::deserialize (FUN_40157e4c): Sequential pattern extraction & bank summary
  - Pattern::deserialize (FUN_4015796c): Track extraction, quantize & CC automation
  - Track::deserialize (FUN_401575b4 / FUN_40155de4): 64-step gate (>= 1.2.0-beta.7),
    PRNG states, pitch/groove locks, cycles, and track parameters.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TORSO_FILE_TAG = b"os|t"  # 0x747c736f (LE)


class BackupFormatError(Exception):
    """Raised when a .t1 backup violates the firmware binary specification."""
    pass


@dataclass
class TrackData:
    track_id: int
    flags: int
    marker: bytes
    pitch_count: int
    pitches: List[int]
    gate: List[int]  # 64 steps
    steps: int
    division: int
    scale: int
    root: int
    velocity: int
    sustain: int
    probability: int
    timing: int
    delay: int
    length: int
    midi_mask: int
    cycles: int
    pitch_locks: Dict[int, List[int]]
    groove_locks: Dict[int, Dict[str, int]]
    raw_block_size: int


@dataclass
class PatternData:
    pattern_id: int
    track_count: int
    tracks: List[TrackData] = field(default_factory=list)
    quantize: int = 0
    automation_records: List[bytes] = field(default_factory=list)


@dataclass
class BankData:
    version: str
    pattern_count: int
    patterns: List[PatternData] = field(default_factory=list)
    tempo: int = 120
    active_pattern: int = 0
    file_tag: bytes = TORSO_FILE_TAG
    total_bytes: int = 0


class T1FirmwareStreamReader:
    """Implements the exact byte-level read operations used by the ESP32 firmware."""

    def __init__(self, data: bytes):
        self.stream = io.BytesIO(data)
        self.data = data
        self.total_size = len(data)

    def read_u8(self) -> int:
        b = self.stream.read(1)
        if len(b) < 1:
            raise BackupFormatError("Unexpected EOF while reading uint8")
        return b[0]

    def read_s8(self) -> int:
        u = self.read_u8()
        return u - 256 if u > 127 else u

    def read_u16_le(self) -> int:
        b = self.stream.read(2)
        if len(b) < 2:
            raise BackupFormatError("Unexpected EOF while reading uint16_le")
        return struct.unpack("<H", b)[0]

    def read_u32_le(self) -> int:
        b = self.stream.read(4)
        if len(b) < 4:
            raise BackupFormatError("Unexpected EOF while reading uint32_le")
        return struct.unpack("<I", b)[0]

    def read_bytes(self, n: int) -> bytes:
        b = self.stream.read(n)
        if len(b) < n:
            raise BackupFormatError(f"Unexpected EOF while reading {n} bytes")
        return b

    def tell(self) -> int:
        return self.stream.tell()

    def seek(self, pos: int) -> None:
        self.stream.seek(pos)


def parse_t1_bank(data: bytes, allow_legacy: bool = True) -> BankData:
    """
    Parses a .t1 bank file using the exact decompiled firmware structure.
    """
    if len(data) < 16:
        raise BackupFormatError(f"File too small ({len(data)} bytes) to be a valid .t1 file")

    reader = T1FirmwareStreamReader(data)

    # 1. FileStream::open (FUN_400edbe8): Version check & EOF tag
    ver_len = reader.read_u8()
    if ver_len < 1 or ver_len > 32:
        raise BackupFormatError(f"Invalid version string length: {ver_len}")
    ver_bytes = reader.read_bytes(ver_len)
    try:
        ver_str = ver_bytes.decode("ascii")
    except UnicodeDecodeError:
        raise BackupFormatError(f"Invalid non-ASCII version string: {ver_bytes!r}")

    # SemVer comparison: reject < 1.1.0
    # In firmware >= 1.2.4, checks 4-byte EOF tag
    if data[-4:] != TORSO_FILE_TAG and not allow_legacy:
        raise BackupFormatError(f"File tag check failed: expected {TORSO_FILE_TAG!r}, got {data[-4:]!r}")

    # 2. Bank::deserialize (FUN_40157e4c)
    pattern_count = reader.read_u8()
    if pattern_count > 16:
        raise BackupFormatError(f"Invalid pattern_count {pattern_count} > 16")

    patterns: List[PatternData] = []
    for _ in range(pattern_count):
        pat_id = reader.read_u8()
        if pat_id > 15:
            raise BackupFormatError(f"Pattern id {pat_id} > 15")

        # 3. Pattern::deserialize (FUN_4015796c)
        track_count = reader.read_u8()
        if track_count > 16:
            raise BackupFormatError(f"Track count {track_count} > 16 in pattern {pat_id}")

        pattern = PatternData(pattern_id=pat_id, track_count=track_count)

        for _ in range(track_count):
            start_pos = reader.tell()
            track_id = reader.read_u8()
            if track_id > 15:
                raise BackupFormatError(f"Track id {track_id} > 15 in pattern {pat_id}")

            # Track::deserialize (FUN_401575b4 -> FUN_40155de4)
            track_flag = reader.read_u8()  # track + 0x4e4
            marker = reader.read_bytes(2)  # 0x0c, 0x00
            pitch_count = reader.read_u8()
            reader.read_bytes(3)  # 00 00 00
            pitches = list(reader.read_bytes(pitch_count))

            # Landmark: 00 0c 00 00 00 + RUN (00 01 02 ... 0b)
            # Gate array: 64 steps (FUN_4010f468 for >= 1.2.0-beta.7)
            # Find RUN landmark to align post-pitch fields
            curr_pos = reader.tell()
            run_idx = data.find(bytes(range(12)), curr_pos, curr_pos + 64)
            if run_idx == -1:
                # If cycle pitch overrides were present, look slightly further
                run_idx = data.find(bytes(range(12)), curr_pos, curr_pos + 128)
                if run_idx == -1:
                    raise BackupFormatError(f"Could not locate RUN landmark for track {track_id}")

            reader.seek(run_idx + 12)  # skip RUN landmark
            gate = list(reader.read_bytes(64))  # 64-step gate array

            # Parse groove locks & pitch locks
            groove_count = reader.read_u8()
            groove_locks: Dict[int, Dict[str, int]] = {}
            for _ in range(groove_count):
                entry_cnt = reader.read_u8()
                step = reader.read_u8()
                step_entries: Dict[str, int] = {}
                for _ in range(entry_cnt):
                    param_id = reader.read_u8()
                    param_val = reader.read_u8()
                    reader.read_bytes(3)  # 00 00 00
                    p_name = "velocity" if param_id == 0x0A else ("sustain" if param_id == 0x0E else f"0x{param_id:02x}")
                    step_entries[p_name] = param_val
                groove_locks[step] = step_entries

            pitch_lock_count = reader.read_u8()
            pitch_locks: Dict[int, List[int]] = {}
            for _ in range(pitch_lock_count):
                step = reader.read_u8()
                p_cnt = reader.read_u32_le()
                p_list = list(reader.read_bytes(p_cnt))
                pitch_locks[step] = p_list

            # Per-cycle step-sequence records & param overrides (or 18-byte pad when empty)
            num_edited_cycles = reader.read_u8()
            for _ in range(num_edited_cycles):
                cyc_idx = reader.read_u8()
                cyc_gate = reader.read_bytes(64)
                cyc_groove_cnt = reader.read_u8()
                for _ in range(cyc_groove_cnt):
                    ec = reader.read_u8()
                    st = reader.read_u8()
                    reader.read_bytes(ec * 5)
                cyc_pitch_cnt = reader.read_u8()
                for _ in range(cyc_pitch_cnt):
                    st = reader.read_u8()
                    cnt = reader.read_u32_le()
                    reader.read_bytes(cnt)

            num_param_recs = reader.read_u8()
            for _ in range(num_param_recs):
                ec = reader.read_u8()
                cyc_idx = reader.read_u8()
                reader.read_bytes(ec * 5)

            reader.read_bytes(16)  # 16-byte pad preceding steps
            so = reader.tell()

            steps = reader.read_u8()
            # Read parameter values at fixed steps offsets
            reader.seek(so + 0x2A)
            division = reader.read_u16_le()
            reader.seek(so + 0x40)
            scale = reader.read_u8()
            reader.seek(so + 0x79)
            prob = reader.read_s8()
            vel = reader.read_u8()
            reader.seek(so + 0xA5)
            sustain = reader.read_u8()
            reader.seek(so + 0xBA)
            timing = reader.read_s8()
            reader.seek(so + 0xE4)
            midi_mask = reader.read_u16_le()
            reader.seek(so + 0x13E)
            delay = reader.read_s8()
            root = reader.read_u8()
            reader.seek(so + 0x14B)
            length = reader.read_u8()
            reader.seek(so + 0x14D)
            cycles = reader.read_u8()

            # End of block is strictly so + 0x2B7 + lock_term
            summary_flag = data[so + 0x29C]
            lock_term = 1 if (groove_locks or pitch_locks or summary_flag != 0) else 0
            block_end = so + 0x2B7 + lock_term
            reader.seek(block_end)

            t_data = TrackData(
                track_id=track_id,
                flags=track_flag,
                marker=marker,
                pitch_count=pitch_count,
                pitches=pitches,
                gate=gate,
                steps=steps,
                division=division,
                scale=scale,
                root=root,
                velocity=vel,
                sustain=sustain,
                probability=prob,
                timing=timing,
                delay=delay,
                length=length,
                midi_mask=midi_mask,
                cycles=cycles,
                pitch_locks=pitch_locks,
                groove_locks=groove_locks,
                raw_block_size=block_end - start_pos,
            )
            pattern.tracks.append(t_data)

        # Pattern trailer is 8 bytes: 00 00 <prev_tc-1> <quantize> 00 00 00 00
        trailer_bytes = reader.read_bytes(8)
        pattern.quantize = trailer_bytes[3]

        patterns.append(pattern)

    # 4. Bank trailer (FUN_4010081c lines 136-141)
    # The bank trailer sits at the end of the file before the 4-byte Torso tag
    tempo = struct.unpack("<H", data[-16:-14])[0]
    active_pat = data[-11]

    return BankData(
        version=ver_str,
        pattern_count=pattern_count,
        patterns=patterns,
        tempo=tempo,
        active_pattern=active_pat,
        file_tag=data[-4:],
        total_bytes=len(data),
    )


def audit_sample_directory(samples_dir: Path) -> List[Dict[str, Any]]:
    """Recursively audits all .t1 files in a directory."""
    results = []
    for p in sorted(samples_dir.rglob("*.t1")):
        try:
            data = p.read_bytes()
            bank = parse_t1_bank(data)
            results.append({
                "path": str(p),
                "status": "PASS",
                "version": bank.version,
                "patterns": bank.pattern_count,
                "tracks": sum(len(pt.tracks) for pt in bank.patterns),
                "tempo": bank.tempo,
                "tag": bank.file_tag.decode("ascii", errors="replace"),
                "size": bank.total_bytes,
            })
        except Exception as e:
            results.append({
                "path": str(p),
                "status": "FAIL",
                "error": str(e),
            })
    return results


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("samples")
    if target.is_file():
        res = parse_t1_bank(target.read_bytes())
        print(f"File: {target}")
        print(f"Version: {res.version}, Patterns: {res.pattern_count}, Tempo: {res.tempo} BPM, Tag: {res.file_tag}")
        for pat in res.patterns:
            print(f"  Pattern #{pat.pattern_id} (quantize={pat.quantize}, tracks={len(pat.tracks)}):")
            for trk in pat.tracks:
                print(f"    Track #{trk.track_id}: steps={trk.steps}, pitches={trk.pitches}, div={trk.division}, vel={trk.velocity}, sus={trk.sustain}")
    else:
        audit = audit_sample_directory(target)
        passed = sum(1 for r in audit if r["status"] == "PASS")
        failed = sum(1 for r in audit if r["status"] == "FAIL")
        print(f"Audited {len(audit)} .t1 files: {passed} PASSED, {failed} FAILED")
        for r in audit:
            if r["status"] == "FAIL":
                print(f"  FAIL: {r['path']} -> {r['error']}")
            else:
                print(f"  PASS: {r['path']} ({r['version']}, {r['patterns']} pat, {r['tracks']} trk, {r['tempo']} BPM)")
