# -*- coding: utf-8 -*-
import sys
from pptx import Presentation
from pptx.util import Emu

path = r"C:\Users\jiawa\Desktop\Gesture_Bridge_三分钟路演.pptx"
prs = Presentation(path)
print("SLIDE SIZE:", prs.slide_width, prs.slide_height,
      "=> EMU", Emu(prs.slide_width).inches, "x", Emu(prs.slide_height).inches, "in")
for i, slide in enumerate(prs.slides):
    print("\n==================== SLIDE", i+1, "====================")
    print("layout:", slide.slide_layout.name)
    for sh in slide.shapes:
        kind = sh.shape_type
        name = sh.name
        has_tf = sh.has_text_frame
        print(f"  [shape] name={name!r} type={kind} id={sh.shape_id}")
        if has_tf:
            for p in sh.text_frame.paragraphs:
                runs_txt = "".join(r.text for r in p.runs)
                if runs_txt.strip() or p.text.strip():
                    print(f"      P(lvl{p.level}): {p.text!r}")
        if sh.has_table:
            tbl = sh.table
            for r_i, row in enumerate(tbl.rows):
                cells = [c.text for c in row.cells]
                print(f"      ROW{r_i}: {cells}")
