#!/usr/bin/env python3
"""Run-aligned diff of arbitrary blocks (by find_runs index). Anchors at `run` and
also reports steps-relative offset. Shows offsets where the blocks differ."""
import os,sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,ROOT); os.chdir(ROOT)
import t1_format as F
TAIL=F.TAIL_AFTER_STEPS
def steps_off(data,run,hi):
    t=F.parse_track(data,run,block_hi=hi)
    term=1 if t["summary_form"] else 0
    return t["block_end"]-TAIL-term
def main():
    path=sys.argv[1]; labels_idx=sys.argv[2:]  # like CC:5 FX:22 Note:30
    data=open(path,"rb").read()
    runs=F.find_runs(data)
    starts=[F._pitch_count_and_start(data,r)[1] for r in runs]
    his=starts[1:]+[len(data)]
    items=[]
    for li in labels_idx:
        lab,idx=li.split(":"); idx=int(idx)
        run=runs[idx]; so=steps_off(data,run,his[idx])
        items.append((lab,run,so,his[idx]))
    print("# blocks:", [(l,hex(r),hex(s)) for l,r,s,h in items])
    # diff run-relative from run-0x40 to run+0x40
    print("## run-relative diffs (run-0x40 .. run+0x60):")
    for off in range(-0x40,0x60):
        vals=[data[r+off] for l,r,s,h in items]
        if len(set(vals))>1:
            print(f"  run{off:+#05x}: "+" ".join(f"{l}={data[r+off]:#04x}" for l,r,s,h in items))
    # diff steps-relative full region
    print("## steps-relative diffs (0..0x2b7):")
    for off in range(0,TAIL):
        vals=[data[s+off] for l,r,s,h in items]
        if len(set(vals))>1:
            print(f"  steps+{off:#05x}: "+" ".join(f"{l}={data[s+off]:#04x}" for l,r,s,h in items))
if __name__=="__main__": main()
