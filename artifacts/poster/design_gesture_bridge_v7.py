"""Make a minimal Gesture Bridge poster focused on gesture-to-speech."""

import json
import math
import struct
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from design_gesture_bridge_v4 import FONT_FILES, MM, Poster
from design_gesture_bridge_v5 import CHAINS, LANDMARKS

ROOT = Path(__file__).resolve().parent
STEM = "gesture-bridge-poster-v7"
WIDTH, HEIGHT = 800, 1800
PAPER = "#F5F4EE"
INK = "#222622"
GRAY = "#767A73"
HAND_FILL = "#EAEAE2"
ACCENT = "#D9432D"

FONT_FILES["Brand"] = ("arialbd.ttf", "Arial", "700")
pdfmetrics.registerFont(TTFont("Brand", "C:/Windows/Fonts/arialbd.ttf"))

# Joint locations follow the existing 21-point hand layout. This outline
# represents a generic example gesture, not a universal sign for the phrase.
HAND_OUTLINE = [
    ("M", 100, 702),
    ("C", 90, 674, 65, 650, 49, 608), ("L", -9, 432),
    ("C", -16, 409, -10, 396, 2, 398),
    ("C", 14, 401, 17, 414, 21, 428), ("L", 52, 513),
    ("C", 54, 519, 59, 521, 61, 514), ("L", 51, 355),
    ("C", 49, 336, 57, 325, 68, 327),
    ("C", 80, 328, 86, 340, 88, 355), ("L", 106, 491),
    ("C", 107, 499, 113, 500, 114, 491), ("L", 117, 308),
    ("C", 117, 289, 125, 278, 136, 280),
    ("C", 148, 282, 152, 295, 152, 310), ("L", 163, 488),
    ("C", 164, 500, 173, 503, 177, 490), ("L", 194, 337),
    ("C", 197, 318, 205, 309, 216, 313),
    ("C", 228, 316, 231, 330, 230, 345), ("L", 217, 514),
    ("C", 217, 535, 222, 551, 233, 558), ("L", 297, 495),
    ("C", 310, 482, 325, 483, 332, 492),
    ("C", 340, 503, 334, 515, 325, 526), ("L", 253, 608),
    ("C", 235, 632, 216, 658, 207, 703), ("Z",),
]


class GestureSpeechPoster(Poster):
    """Reuse drawing and print export without reusing previous compositions."""

    def __init__(self):
        self.pdf = canvas.Canvas(
            str(ROOT / f"{STEM}-80x180cm.pdf"),
            pagesize=(WIDTH * MM, HEIGHT * MM),
            pageCompression=1,
        )
        self.pdf.setTitle("Gesture Bridge")
        self.pdf.setAuthor("Gesture Bridge")
        self.pdf.setSubject("Gesture recognition to confirmed speech")
        self.pdf.scale(MM, MM)
        self.parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="800mm" '
            'height="1800mm" viewBox="0 0 800 1800" role="img" '
            'aria-labelledby="title description">',
            '<title id="title">Gesture Bridge</title>',
            '<desc id="description">A minimal gesture-to-speech poster. '
            'An open hand with anatomical recognition landmarks leads '
            'into a sound wave and the spoken example 我想喝水。'
            'The phrase is an expression example, not a universal hand sign.'
            '</desc>',
        ]
        self.text_bounds = []

    def save(self):
        self.pdf.showPage()
        self.pdf.save()
        self.parts.append("</svg>")
        svg = "\n".join(self.parts)
        (ROOT / f"{STEM}.svg").write_text(svg, encoding="utf-8")
        (ROOT / f"{STEM}.html").write_text(
            '<!doctype html><html lang="zh-CN"><head>'
            '<meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1">'
            '<title>Gesture Bridge</title><style>'
            '*{box-sizing:border-box}body{margin:0;background:#dfdfd7}'
            'main{width:min(100%,800px);margin:0 auto}'
            'svg{display:block;width:100%;height:auto}'
            '@page{size:800mm 1800mm;margin:0}'
            '@media print{main{width:800mm;margin:0}'
            'svg{width:800mm;height:1800mm}}'
            '</style></head><body><main>' + svg
            + '</main></body></html>', encoding="utf-8",
        )
        outside = [
            b for b in self.text_bounds
            if b["x"] < 0 or b["right"] > WIDTH
            or b["top"] < 0 or b["bottom"] > HEIGHT
        ]
        report = {
            "project_name": "Gesture Bridge",
            "dimensions_mm": [800, 1800],
            "concept": "Gesture recognition to confirmed speech",
            "landmark_count": len(LANDMARKS),
            "text_outside_page": outside,
            "expression_example": "我想喝水。",
            "waveform_source": "headvoice/audio/AA.pcm (display envelope)",
            "gesture_semantics": "Illustrative; no universal sign claimed",
        }
        (ROOT / f"{STEM}-check.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if outside:
            raise ValueError(outside)


def hand_point(point):
    return 98 + point[0] * .95, 405 + point[1] * .95


def draw_hand(poster):
    commands = []
    for op, *values in HAND_OUTLINE:
        out = [op]
        for i in range(0, len(values), 2):
            out.extend(hand_point(values[i:i + 2]))
        commands.append(tuple(out))
    poster.path(commands, fill=HAND_FILL, stroke=INK, width=1.9)
    for chain in CHAINS:
        poster.path(
            [("M", *hand_point(LANDMARKS[chain[0]]))]
            + [("L", *hand_point(LANDMARKS[i])) for i in chain[1:]],
            stroke=INK, width=.85,
        )
    for index, point in enumerate(LANDMARKS):
        color = ACCENT if index in [4, 8, 12, 16, 20] else PAPER
        poster.circle(*hand_point(point), 3, fill=color, stroke=INK, width=.6)

    # Four quiet corner marks indicate the camera recognition area.
    for x, y, dx, dy in [(72, 642, 1, 1), (446, 642, -1, 1),
                         (72, 1100, 1, -1), (446, 1100, -1, -1)]:
        poster.path([
            ("M", x, y + dy * 18), ("L", x, y),
            ("L", x + dx * 18, y),
        ], stroke=GRAY, width=.8)
    poster.text("手势输入", 73, 606, 23, "CNB", INK)


def draw_voice(poster):
    sx, sy = hand_point(LANDMARKS[4])
    poster.path([
        ("M", sx, sy),
        ("C", 425, sy, 430, 925, 455, 925),
        ("L", 687, 925),
        ("C", 705, 975, 650, 1011, 650, 1076),
    ], stroke=ACCENT, width=2.1)

    # Compress the stored sample into a recognizable audio-envelope symbol.
    audio_path = ROOT.parent.parent / "headvoice" / "audio" / "AA.pcm"
    samples = [value[0] for value in struct.iter_unpack(
        "<h", audio_path.read_bytes())]
    threshold = max(abs(value) for value in samples) * .02
    active = [i for i, value in enumerate(samples) if abs(value) > threshold]
    samples = samples[max(0, active[0] - 128):active[-1] + 129]
    levels = []
    for i in range(24):
        window = samples[len(samples) * i // 24:len(samples) * (i + 1) // 24]
        levels.append(math.sqrt(sum(v * v for v in window) / len(window)))
    peak = max(levels) or 1
    for i, level in enumerate(levels):
        amplitude = 3 + 34 * math.sqrt(level / peak)
        x = 463 + i * 9
        poster.line(x, 925 - amplitude, x, 925 + amplitude, ACCENT, 2.8)

    poster.path([
        ("M", 284, 1144), ("L", 624, 1144),
        ("L", 650, 1076), ("L", 690, 1144),
        ("L", 800, 1144), ("L", 800, 1538),
        ("L", 284, 1538), ("Z",),
    ], fill=ACCENT)
    poster.text("语音输出 / 表达示例", 328, 1204, 17, "CN", PAPER)
    poster.text("我想", 328, 1320, 96, "CNB", PAPER, tracking=-3)
    poster.text("喝水。", 328, 1441, 96, "CNB", PAPER, tracking=-3)


def main():
    assert len(LANDMARKS) == 21
    p = GestureSpeechPoster()
    p.rect(0, 0, WIDTH, HEIGHT, PAPER)
    p.text("Gesture Bridge", 55, 104, 54, "Brand", INK, tracking=-1.8)
    p.text("手势转语音辅助沟通设备", 58, 147, 18, "CN", GRAY)

    p.text("把手势，", 48, 300, 98, "CNB", INK, tracking=-5)
    p.text("说出来。", 170, 430, 108, "CNB", INK, tracking=-5)
    p.text("GESTURE TO VOICE", 55, 491, 16,
           "Latin", ACCENT, tracking=1.2)

    draw_hand(p)
    draw_voice(p)

    for x, text in [(55, "手势识别"), (332, "确认表达"), (610, "语音播报")]:
        p.text(text, x, 1630, 21, "CNB", INK)
    for x in [200, 477]:
        p.line(x, 1622, x + 72, 1622, ACCENT, .9)
        p.arrow(x + 72, 1622, colour=ACCENT, size=5)
    p.text("Gesture Bridge / 产品概念设计", 55, 1750, 10.5, "CN", GRAY)
    p.save()


if __name__ == "__main__":
    main()
