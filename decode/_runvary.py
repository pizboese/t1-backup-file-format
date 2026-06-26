#!/usr/bin/env python3
"""Run-relative varying-offset reporter across a group of find_runs block indices.
Scans from run-0x60 to run+0x60 (gate/lock/header region) to catch fields OUTSIDE
the steps region (e.g. mute, gate)."""
import os,sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,ROOT); os.chdir(ROOT)
import t1_format as F
data=open(sys.argv[1],"rb").read()
idxs=[int(x) for x in sys.argv[2:]]
runs=F.find_runs(data)
rs=[runs[i] for i in idxs]
print(f"# run-relative diffs, blocks {idxs}")
for off in range(-0x60,0x70):
    vals=[data[r+off] for r in rs]
    if len(set(vals))>1:
        print(f"  run{off:+#06x}: {vals}")
