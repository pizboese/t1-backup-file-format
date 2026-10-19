#!/usr/bin/env python3
"""
test_firmware_parser.py — Verification of .t1 backup parsing against firmware ground truth.
"""

import unittest
from pathlib import Path

from t1_firmware_parser import (
    TORSO_FILE_TAG,
    BackupFormatError,
    BankData,
    PatternData,
    TrackData,
    parse_t1_bank,
)

SAMPLES_DIR = Path(__file__).parent / "samples"


class TestFirmwareParser(unittest.TestCase):
    """Test suite verifying .t1 bank parsing against Torso firmware rules."""

    def test_torso_tag_enforcement(self) -> None:
        """Firmware strictly requires 0x747c736f ('os|t') at EOF."""
        sample_path = SAMPLES_DIR / "01_pulse_sweep/1pulses.t1"
        raw = sample_path.read_bytes()
        self.assertEqual(raw[-4:], TORSO_FILE_TAG)

        # Corrupt tag should raise BackupFormatError when legacy mode is disabled
        corrupt = raw[:-4] + b"FAIL"
        with self.assertRaises(BackupFormatError):
            parse_t1_bank(corrupt, allow_legacy=False)

    def test_version_header_parsing(self) -> None:
        """Verify length-prefixed ASCII SemVer header."""
        sample_path = SAMPLES_DIR / "03_strides/manual_5tracks.t1"
        raw = sample_path.read_bytes()
        ver_len = raw[0]
        ver_str = raw[1 : 1 + ver_len].decode("ascii")
        self.assertEqual(ver_len, 5)
        self.assertEqual(ver_str, "2.1.4")

    def test_gate_array_is_64_bytes(self) -> None:
        """Gate array loop reads 64 steps."""
        sample_path = SAMPLES_DIR / "01_pulse_sweep/4pulses.t1"
        bank = parse_t1_bank(sample_path.read_bytes())
        self.assertGreater(bank.pattern_count, 0)
        self.assertGreater(len(bank.patterns[0].tracks), 0)
        trk = bank.patterns[0].tracks[0]
        self.assertEqual(len(trk.gate), 64)
        self.assertEqual(sum(trk.gate), 4)

    def test_bank_trailer_tempo(self) -> None:
        """Verify bank trailer stores tempo as uint16 LE BPM."""
        sample_default = SAMPLES_DIR / "01_pulse_sweep/1pulses.t1"
        bank = parse_t1_bank(sample_default.read_bytes())
        self.assertEqual(bank.tempo, 120)

        sample_fast = SAMPLES_DIR / "20_backup1_params/2.t1"
        bank_fast = parse_t1_bank(sample_fast.read_bytes())
        self.assertEqual(bank_fast.tempo, 278)

        sample_slow = SAMPLES_DIR / "20_backup1_params/1.t1"
        bank_slow = parse_t1_bank(sample_slow.read_bytes())
        self.assertEqual(bank_slow.tempo, 24)

    def test_groove_locks_decoding(self) -> None:
        """Verify groove lock IDs match firmware (0x0A=velocity, 0x0E=sustain)."""
        sample_locks = SAMPLES_DIR / "08_perstep_groove/bank.t1"
        bank = parse_t1_bank(sample_locks.read_bytes())
        trk = bank.patterns[0].tracks[0]
        self.assertTrue(len(trk.groove_locks) > 0)
        for step, locks in trk.groove_locks.items():
            for param in locks:
                self.assertIn(param, ("velocity", "sustain"))

    def test_pitch_locks_polyphony(self) -> None:
        """Verify polyphonic pitch locks parsing."""
        sample_poly = SAMPLES_DIR / "09_perstep_polyphony/bank.t1"
        bank = parse_t1_bank(sample_poly.read_bytes())
        trk = bank.patterns[0].tracks[0]
        self.assertTrue(len(trk.pitch_locks) > 0)
        for step, notes in trk.pitch_locks.items():
            self.assertGreater(len(notes), 0)

    def test_cycle_records_parsing(self) -> None:
        """Verify cycle records and param overrides parse without shifting steps."""
        sample_cyc = SAMPLES_DIR / "15_steps64_cycles/0.t1"
        bank = parse_t1_bank(sample_cyc.read_bytes())
        self.assertEqual(bank.pattern_count, 2)
        self.assertEqual(len(bank.patterns[1].tracks), 12)


if __name__ == "__main__":
    unittest.main()
