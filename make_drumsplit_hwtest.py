#!/usr/bin/env python3
"""make_drumsplit_hwtest.py — build a hardware-verification bank for DRUM-TRACK SPLITTING and
SPARSE TRACK POSITIONS, from "The Dawning" MIDI. Emits a fresh single-bank backup zip.

Each pattern places its melodic SMF tracks on slots 1.. and explodes its Drums part into one T-1
track per drum sound on fixed slots (kick=16, snare=15, closed-hat=14, open-hat=13, clap=12, the
rest just below). This exercises: absolute track positions with gaps (melodic 1.. / drums 9..16),
the anchored priority slots, and single-pitch drum tracks that carry NO per-step pitch lock.

Run:  python3 make_drumsplit_hwtest.py   ->  hwtest/drumsplit_dawning.t1 + .zip
"""
import os

import midi_to_t1 as M

DAWN = "midi/The Dawning"
PATTERNS = [                       # (slot, [melodic SMF files], drums file)
    (0, ["Pattern1_Track1.mid", "Pattern1_Track2.mid"], "Pattern1_Drums.mid"),
    (1, ["Pattern2_Track1.mid", "Pattern2_Track2.mid", "Pattern2_Track3.mid"], "Pattern2_Drums.mid"),
    (2, ["Pattern3_Track1.mid", "Pattern3_Track2.mid", "Pattern3_Track3.mid"], "Pattern3_Drums.mid"),
]
OUT_T1 = "hwtest/drumsplit_dawning.t1"


def build_plan():
    # 'auto' cycles (the default): voices that span >1 bar become cycles (each 16-step bar -> a
    # cycle), carrying per-bar velocity/length (e.g. the toms' bar-2 dynamics) into per-cycle locks;
    # drum tracks additionally share one kit-wide cycle count so they stay phase-locked.
    cyc = {"cycles": "auto", "steps": 16}
    pats = []
    for slot, mel, drums in PATTERNS:
        tracks = [{"midi": os.path.join(DAWN, f), "track": i + 1, **cyc}
                  for i, f in enumerate(mel)]                 # melodic -> slots 1..k
        tracks.append({"midi": os.path.join(DAWN, drums), "drum_split": True, **cyc})  # drums 9..16
        pats.append({"slot": slot, "tracks": tracks})
    return {"backup": "new", "bank": 0, "div": 16, "patterns": pats}


def main():
    template = M.load_template(M.DEFAULT_TEMPLATE)
    bank, slot, src = M.run_plan(build_plan(), template)
    with open(OUT_T1, "wb") as f:
        f.write(bank)
    out_zip = os.path.splitext(OUT_T1)[0] + ".zip"
    M.write_backup_zip(bank, out_zip, slot=slot, src_zip=None)   # fresh single-bank file
    print(f"wrote {OUT_T1} ({len(bank)} B) and {out_zip} (restore via T-1 Backup menu, bank {slot})")


if __name__ == "__main__":
    main()
