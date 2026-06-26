#!/usr/bin/env python3
"""Find ALL track blocks regardless of scale-table landmark, by locating the
pitch marker `0c 00 <pc> 00 00 00` then the u32 scale-degree-table count.
Robust to CC/FX/custom-scale blocks that lose the chromatic `00 01..0b` landmark."""
import os,sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,ROOT); os.chdir(ROOT)
data=open(sys.argv[1],"rb").read()
blocks=[]
i=0
while i < len(data)-12:
    if data[i]==0x0c and data[i+1]==0x00 and data[i+3:i+6]==b"\x00\x00\x00":
        pc=data[i+2]
        if 1<=pc<=6:
            # pitches: pc words at i+6
            poff=i+6
            scoff=poff+2*pc
            cnt=int.from_bytes(data[scoff:scoff+4],"little")
            if 1<=cnt<=12 and scoff+4+cnt<=len(data):
                degs=list(data[scoff+4:scoff+4+cnt])
                if degs==sorted(degs) and all(d<12 for d in degs):
                    pitches=[int.from_bytes(data[poff+2*k:poff+2*k+2],"little") for k in range(pc)]
                    blocks.append((i,pc,pitches,cnt,degs))
                    i=scoff+4+cnt; continue
    i+=1
print(f"# {len(blocks)} blocks")
prev=None
for k,(off,pc,pit,cnt,degs) in enumerate(blocks):
    d=off-prev if prev is not None else 0
    gap=" <== GAP" if d>900 else ""
    print(f"{k:3d} {off:#08x} d={d:5d} pc={pc} pitch={pit} scaleCnt={cnt} degs={degs}{gap}")
    prev=off
