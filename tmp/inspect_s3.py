# -*- coding: utf-8 -*-
from pptx import Presentation
from pptx.util import Emu, Pt

path = r"C:\Users\jiawa\Desktop\Gesture_Bridge_三分钟路演.pptx"
prs = Presentation(path)
slide = prs.slides[2]  # slide 3
def inch(v): return round(Emu(v).inches, 2) if v is not None else None
for sh in slide.shapes:
    if not sh.has_text_frame:
        continue
    txt = sh.text_frame.text
    if not txt.strip():
        continue
    # font size of first run
    fs = None; bold=None; color=None; align=None
    for p in sh.text_frame.paragraphs:
        align = p.alignment
        for r in p.runs:
            if r.font.size: fs = r.font.size.pt
            bold = r.font.bold
            try:
                if r.font.color and r.font.color.type is not None:
                    color = str(r.font.color.rgb)
            except Exception:
                pass
            break
        if fs: break
    print(f"name={sh.name!r} id={sh.shape_id} pos=({inch(sh.left)},{inch(sh.top)}) size=({inch(sh.width)}x{inch(sh.height)}) font={fs} bold={bold} color={color} align={align}")
    print(f"    TEXT={txt!r}")
