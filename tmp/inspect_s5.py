# -*- coding: utf-8 -*-
from pptx import Presentation
from pptx.util import Emu

path = r"C:\Users\jiawa\Desktop\Gesture_Bridge_三分钟路演.pptx"
prs = Presentation(path)
slide = prs.slides[4]  # slide 5
def inch(v): return round(Emu(v).inches, 2) if v is not None else None
for sh in slide.shapes:
    if not sh.has_text_frame: continue
    txt = sh.text_frame.text
    if not txt.strip(): continue
    fs=None
    for p in sh.text_frame.paragraphs:
        for r in p.runs:
            if r.font.size: fs=r.font.size.pt
            break
        if fs: break
    nruns = sum(len(p.runs) for p in sh.text_frame.paragraphs)
    print(f"id={sh.shape_id} name={sh.name!r} pos=({inch(sh.left)},{inch(sh.top)}) size=({inch(sh.width)}x{inch(sh.height)}) font={fs} runs={nruns}")
    print(f"    {txt!r}")
