#!/usr/bin/env python3
"""
t1_blockdiff.py — compare individual track BLOCKS across patterns/banks, aligned
to the `00 01 .. 0b` landmark (`run`), so the variable-length lock lists don't
throw the byte offsets out of register.

Purpose: isolate the per-track "random buffer" inside the 695-byte steps-region.
If you take one track, copy it across several patterns, and regenerate ONLY the
random sequence on each copy, then by the format's determinism the blocks differ
*only* in the random bytes. This tool aligns those blocks and reports:
  - which offsets are CONSTANT  -> structured parameters (incl. still-undecoded)
  - which offsets VARY          -> the random buffer (carve [random | params])

Usage:
  t1_blockdiff.py FILE.t1 [FILE2.t1 ...]            # all blocks across all files
  t1_blockdiff.py FILE.t1:0 FILE.t1:1 FILE.t1:2     # specific (file:block_index)
  t1_blockdiff.py --steps-only FILE.t1 ...          # restrict report to steps-region

Offsets are reported relative to `run` and, once past `steps`, also relative to
`steps` (the field the known params hang off: division steps+0x2a, scale +0x40,
velocity +0x7b, sustain +0xa5, mask +0xe4, root +0x13f).
"""
import sys
from t1_format import parse_bank, OFF_LOCKS, _parse_locks, TAIL_AFTER_STEPS

# known field offsets relative to `steps` (for annotation)
STEPS_FIELDS = {
    0x00: "steps", 0x2a: "division.lo", 0x2b: "division.hi", 0x40: "scale",
    0x7b: "velocity", 0xa5: "sustain", 0xe4: "mask.lo", 0xe5: "mask.hi",
    0x13f: "root",
}


def steps_offset(data, run):
    _, _, so = _parse_locks(data, run)
    return so


def collect(specs):
    """Return list of dicts: {label, data, run, so, block_end}."""
    blocks = []
    for spec in specs:
        if ":" in spec and not spec.endswith(".t1"):
            path, idx = spec.rsplit(":", 1)
            idxs = [int(idx)]
        else:
            path, idxs = spec, None
        bank = parse_bank(path)
        data = open(path, "rb").read()
        sel = range(len(bank["tracks"])) if idxs is None else idxs
        for i in sel:
            t = bank["tracks"][i]
            run = t["run"]
            blocks.append({
                "label": f"{path}:{i}",
                "data": data, "run": run,
                "so": steps_offset(data, run),
                "block_end": t["block_end"],
            })
    return blocks


def annotate(rel_run, rel_steps):
    if rel_run < 0x0c:
        return "header/landmark"
    if rel_run < 0x1c:
        return f"GATE+{rel_run - 0x0c:#x}"
    if rel_run < OFF_LOCKS:
        return "pre-lock"
    if rel_steps is None:
        return "lock-list"
    if rel_steps < 0:
        return f"pad(steps{rel_steps:+#x})"
    tag = STEPS_FIELDS.get(rel_steps)
    return f"steps+{rel_steps:#05x}" + (f" [{tag}]" if tag else "")


def sweep(blocks):
    """Steps-aligned: flag offsets whose value changes monotonically (+/-1 per
    block) — the signature of a swept value parameter (e.g. Style=0,1,2,…)."""
    print(f"== steps-region SWEEP over {len(blocks)} blocks (looking for monotonic value) ==")
    for b in blocks:
        print(f"   - {b['label']}")
    mono, varying = [], []
    for k in range(TAIL_AFTER_STEPS):
        vals = [b["data"][b["so"] + k] for b in blocks]
        if len(set(vals)) == 1:
            continue
        varying.append((k, vals))
        d = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        if all(x == 1 for x in d) or all(x == -1 for x in d):
            mono.append((k, vals))
    print(f"\n  {len(varying)} steps-offsets vary; {len(mono)} monotonic (+/-1 per block):\n")
    print("  MONOTONIC (likely the swept value param):")
    for k, vals in mono:
        tag = annotate(0x100 + k, k)
        print(f"    steps+{k:#05x} [{tag}]: {vals}")
    if not mono:
        print("    (none — try a wider value range, or the param isn't a simple +1 counter)")
    print("\n  all VARYING steps-offsets (for manual inspection):")
    for k, vals in varying:
        tag = annotate(0x100 + k, k)
        flag = "  <== MONO" if (k, vals) in mono else ""
        print(f"    steps+{k:#05x} [{tag}]: {vals}{flag}")


def main(argv):
    steps_only = do_sweep = False
    while argv and argv[0].startswith("--"):
        if argv[0] == "--steps-only":
            steps_only = True
        elif argv[0] == "--sweep":
            do_sweep = True
        argv = argv[1:]
    if not argv:
        print(__doc__); return 1
    blocks = collect(argv)
    if len(blocks) < 2:
        print("need >=2 blocks to diff"); return 1
    if do_sweep:
        sweep(blocks); return 0

    so_rel = [b["so"] - b["run"] for b in blocks]
    pre_aligned = len(set(so_rel)) == 1   # lock lists identical -> run-alignment valid pre-steps

    print(f"== block diff: {len(blocks)} blocks ==")
    for b in blocks:
        print(f"   - {b['label']}  run={b['run']:#x} steps=run+{b['so']-b['run']:#x} "
              f"end=run+{b['block_end']-b['run']:#x}")
    if not pre_aligned:
        print(f"   note: steps offset (rel run) differs: {so_rel} -> lock lists differ; "
              f"pre-steps diff suppressed, steps-region aligned by `steps`.")

    runs_out = []      # [section, start_k, end_k] contiguous varying runs
    const = varying = 0

    def scan(section, get_byte, lo, hi):
        nonlocal const, varying
        for k in range(lo, hi):
            vals = [get_byte(b, k) for b in blocks]
            if len(set(vals)) == 1:
                const += 1; continue
            varying += 1
            if runs_out and runs_out[-1][0] == section and k == runs_out[-1][2] + 1:
                runs_out[-1][2] = k
            else:
                runs_out.append([section, k, k])

    # --- pre-steps region: align by run (only meaningful if lock lists match) ---
    if pre_aligned and not steps_only:
        so_r = so_rel[0]
        scan("run", lambda b, k: b["data"][b["run"] + k], 0, so_r)

    # --- steps-region: align by each block's own `steps` offset ---
    scan("steps", lambda b, k: b["data"][b["so"] + k], 0, TAIL_AFTER_STEPS)

    def tag_of(section, k):
        return annotate(k, None) if section == "run" else annotate(0x100 + k, k)

    print(f"\n  CONSTANT: {const} offsets   VARYING: {varying} offsets "
          f"(in {len(runs_out)} runs)\n")
    print("  VARYING runs (candidate random buffer):")
    for section, s, e in runs_out:
        print(f"    {tag_of(section, s):<26} ({e - s + 1:3d} B)")
    if not runs_out:
        print("    (none — blocks are byte-identical; was random actually regenerated?)")

    # flag any VARYING steps-offset that lands on a known param
    hits = [(k, STEPS_FIELDS[k]) for section, s, e in runs_out if section == "steps"
            for k in range(s, e + 1) if k in STEPS_FIELDS]
    if hits:
        print("\n  ⚠ varying offsets hit KNOWN params (expected constant if only random changed):")
        for k, name in hits:
            vals = [b["data"][b["so"] + k] for b in blocks]
            print(f"    steps+{k:#05x} [{name}]: {vals}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
