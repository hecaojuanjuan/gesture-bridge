# -*- coding: utf-8 -*-
from pptx import Presentation

path = r"C:\Users\jiawa\Desktop\Gesture_Bridge_三分钟路演.pptx"
prs = Presentation(path)

def set_text(shape, new_text):
    """Set text on first run of first paragraph, keep its formatting, clear the rest."""
    tf = shape.text_frame
    paras = tf.paragraphs
    first_p = paras[0]
    if not first_p.runs:
        raise RuntimeError(f"shape id={shape.shape_id} first paragraph has no run")
    # keep first run, set text
    first_p.runs[0].text = new_text
    # remove other runs in first paragraph
    for r in first_p.runs[1:]:
        r._r.getparent().remove(r._r)
    # remove any extra paragraphs
    for p in paras[1:]:
        p._p.getparent().remove(p._p)

def by_id(slide, sid):
    for sh in slide.shapes:
        if sh.shape_id == sid:
            return sh
    raise RuntimeError(f"id {sid} not found")

# ---------- SLIDE 3 ----------
s3 = prs.slides[2]
# subtitle
set_text(by_id(s3, 4), "板端已部署真实视觉识别链路；以下为本轮板端实测数据。")
# tile 1: badge / number / label
set_text(by_id(s3, 41), "板端实测")
set_text(by_id(s3, 42), "0.46 秒")
set_text(by_id(s3, 43), "单次手势推理中位数")
# tile 2: badge / number / label
set_text(by_id(s3, 46), "离线运行")
set_text(by_id(s3, 47), "11 类")
set_text(by_id(s3, 48), "官方模型 · 完全板端")
# footnote
set_text(by_id(s3, 54),
         "注：张掌识别链路已在板端跑通并产生完成事件；V 字与整体准确率、喇叭播报仍待真机验收。")

# ---------- SLIDE 5 ----------
s5 = prs.slides[4]
set_text(by_id(s5, 31),
         "当前进度：板端识别链路已部署（152 项主机回归 + 100 项前端测试通过，ESP32-S3 完整编译）；个人词典同步、使用者确认与手势触发播报仍在集成中。")

prs.save(path)
print("SAVED OK")
