#!/usr/bin/env python3
"""Flexible monotonic scan: tests u8, s8, u16le, and s16le interpretations.
Usage: python3 decode/_scan2.py FILE.t1 i0 i1 ...
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import t1_format as F
TAIL = F.TAIL_AFTER_STEPS
KNOWN = {0x00:"steps",0x2a:"div_lo",0x2b:"div_hi",0x40:"scale",0x55:"pitch_run",
0x79:"prob",0x7b:"vel",0xa5:"sus",0xba:"timing",0xe4:"outmask",0x13d:"style",
0x13e:"delay",0x13f:"root",0x146:"tsub",0x14b:"trklen",0x14d:"cycles",0x299:"freediv"}
ZONE_A={0x16,0x68,0x91,0xbb,0xd0,0xfa,0x110,0x126}
def steps_off(data,run,hi):
    t=F.parse_track(data,run,block_hi=hi);term=1 if t['summary_form'] else 0
    return t['block_end']-TAIL-term
def load(path):
    data=open(path,'rb').read();runs=F.find_runs(data)
    starts=[F._pitch_count_and_start(data,r)[1] for r in runs]
    his=starts[1:]+[len(data)]
    return data,[steps_off(data,runs[j],his[j]) for j in range(len(runs))]
def mono(vals):
    d=[b-a for a,b in zip(vals,vals[1:])]
    if all(x>0 for x in d):return '+'
    if all(x<0 for x in d):return '-'
    return None
def tag(off):
    if off in KNOWN:return KNOWN[off]
    for z in ZONE_A:
        if abs(off-z)<=3:return f"~ZA{z:#x}"
    return ""
def main():
    path=sys.argv[1];idxs=[int(x) for x in sys.argv[2:]]
    data,sos=load(path);bs=[sos[i] for i in idxs]
    print(f"# {path} {idxs}")
    print("## u8:")
    for off in range(TAIL):
        v=[data[so+off] for so in bs]
        if len(set(v))>1 and mono(v):print(f"  +{off:#05x} u8 {v} {tag(off)}")
    print("## s8 (signed, catches bipolar wrap):")
    for off in range(TAIL):
        v=[data[so+off]-256 if data[so+off]>127 else data[so+off] for so in bs]
        if len(set(v))>1 and mono(v):
            if not any(data[so+off]>127 for so in bs):continue  # already shown as u8
            print(f"  +{off:#05x} s8 {v} {tag(off)}")
    print("## s16le:")
    for off in range(TAIL-1):
        v=[]
        for so in bs:
            x=data[so+off]|(data[so+off+1]<<8)
            v.append(x-65536 if x>32767 else x)
        if len(set(v))>1 and mono(v):
            # skip pure u8 echoes already found (high byte constant 0)
            hb=set(data[so+off+1] for so in bs)
            print(f"  +{off:#05x} s16 {v} {tag(off)}")
main()
