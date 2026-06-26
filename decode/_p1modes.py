#!/usr/bin/env python3
import os,sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,ROOT); os.chdir(ROOT)
import t1_format as F
data=open('decode/samples/23_modes_routing_global/23_modes_routing_global.t1','rb').read()
# P1 block starts (pitch markers). chromatic: 0x11,0x334,0x657,0x97a,0xc9d ; nonchrom: 0xfba.. 
# Actually use marker offsets. find pitch markers 0c 00 01 00 00 00 in 0..0x1f4b plus the first at 0x0b-ish
# We'll find steps offset via Zone-B terminator: 00 00 00 53 00 at steps+0x295.
def steps_from(start, end):
    last=-1
    for j in range(start, end-1):
        if data[j]==0x53 and data[j-3:j]==b"\x00\x00\x00" and data[j+1]==0:
            last=j
    return last-0x295 if last>0 else None
# block starts for P1: the 5 chromatic (marker = run-... use run from find_runs) + 5 nonchrom markers
runs=F.find_runs(data)
chrom=[r for r in runs if r<0x1f4b]   # 0x17,0x33a,0x65d,0x980,0xca3
nonchrom=[0xfba,0x12d2,0x15ec,0x1907,0x1c25]
# build (start,label) sorted by offset; use marker-ish start
starts=sorted([(r-0x0c,'chr',r) for r in chrom]+[(m,'non',m) for m in nonchrom])
# add boundaries
bounds=[s[0] for s in starts]+[0x1f4b]
sos=[]
for i,(st,lab,anchor) in enumerate(starts):
    so=steps_from(st, bounds[i+1])
    sos.append((st,lab,so))
    print(f'{i} start={st:#x} {lab} steps_off={hex(so) if so else None}')
# Now varying-offset across all 10 P1 blocks (steps-relative)
valid=[so for st,lab,so in sos if so]
print('\\n# steps-relative varying offsets across P1 (10 blocks):')
KNOWN={0x40:'scale',0x7b:'vel',0xa5:'sus',0xe4:'mask',0x13d:'style',0x13f:'root',0x297:'route',0x29c:'lockflag'}
for off in range(0,F.TAIL_AFTER_STEPS):
    vals=[data[so+off] for so in valid]
    if len(set(vals))>1:
        print(f'  steps+{off:#05x} {KNOWN.get(off,"")}: {vals}')
