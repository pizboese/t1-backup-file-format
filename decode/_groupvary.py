#!/usr/bin/env python3
"""For a group of block indices, print every steps-region offset whose value VARIES
across the blocks, showing the per-block values. Reveals laddered/split fields that
aren't strictly monotonic (mute, routing masks, etc.)."""
import os, sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,ROOT); os.chdir(ROOT)
import t1_format as F
TAIL=F.TAIL_AFTER_STEPS
KNOWN={0x00:"steps",0x2a:"div_lo",0x2b:"div_hi",0x40:"scale",0x55:"pitch_run",
0x79:"prob",0x7b:"vel",0x90:"range",0xa5:"sustain",0xba:"timing",0xcf:"voicing",
0xe4:"mask_lo",0xe5:"mask_hi",0xfa:"repeats",0x10f:"accent",0x124:"time_lo",0x125:"time_hi",
0x13a:"rotate",0x13b:"ramp",0x13c:"pace",0x13d:"style",0x13e:"delay",0x13f:"root",
0x146:"timing_sub",0x147:"phrase",0x148:"groove",0x14b:"length",0x14d:"cycles",
0x299:"freediv",0x29a:"timefree",0x29c:"lockflag",0x2a0:"lockcur_lo",0x2b0:"stepgrp",
0x2b5:"end2b5",0x2b6:"end2b6"}
def steps_off(data,run,hi):
    t=F.parse_track(data,run,block_hi=hi)
    term=1 if t["summary_form"] else 0
    return t["block_end"]-TAIL-term
def main():
    path=sys.argv[1]; idxs=[int(x) for x in sys.argv[2:]]
    data=open(path,"rb").read()
    runs=F.find_runs(data)
    starts=[F._pitch_count_and_start(data,r)[1] for r in runs]
    his=starts[1:]+[len(data)]
    sos=[steps_off(data,runs[i],his[i]) for i in idxs]
    print(f"# {path} blocks {idxs}")
    print(f"# steps_offsets: {[hex(s) for s in sos]}")
    for off in range(0,TAIL):
        vals=[data[s+off] for s in sos]
        if len(set(vals))<2: continue
        sv=[v-256 if v>127 else v for v in vals]
        print(f"  +{off:#05x} {KNOWN.get(off,''):10s} u8={vals} s8={sv}")
if __name__=="__main__": main()
