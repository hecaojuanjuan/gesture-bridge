"""Keep the supplied background intact and typeset its lower speech shapes."""

import base64
import hashlib
import json
import math
import struct
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from design_gesture_bridge_v4 import FONT_FILES, MM, Poster

ROOT = Path(__file__).resolve().parent
STEM = "gesture-bridge-poster-v8"
BACKGROUND = ROOT / f"{STEM}-background.jpg"
WIDTH, HEIGHT = 800, 1800
PROTECTED_BOTTOM = 960
INK = "#454A46"

FONT_FILES["OverlayHand"] = ("simkai.ttf", "KaiTi", "400")
pdfmetrics.registerFont(TTFont("OverlayHand", "C:/Windows/Fonts/simkai.ttf"))


class ReferencePoster(Poster):
    """Use the untouched reference as a page background, not a redraw."""

    def __init__(self):
        self.pdf = canvas.Canvas(
            str(ROOT / f"{STEM}-80x180cm.pdf"),
            pagesize=(WIDTH * MM, HEIGHT * MM),
            pageCompression=1,
        )
        self.pdf.setTitle("Gesture Bridge")
        self.pdf.setAuthor("Gesture Bridge")
        self.pdf.setSubject("Original reference with lower-area typography")
        self.pdf.scale(MM, MM)
        self.pdf.drawImage(str(BACKGROUND), 0, 0, width=WIDTH, height=HEIGHT)
        encoded = base64.b64encode(BACKGROUND.read_bytes()).decode("ascii")
        self.parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="800mm" '
            'height="1800mm" viewBox="0 0 800 1800" role="img" '
            'aria-labelledby="title description">',
            '<title id="title">Gesture Bridge</title>',
            '<desc id="description">The user-supplied charcoal and yellow '
            'poster is preserved as an unaltered background. New editable '
            'type and an audio symbol occupy only the lower speech shapes.'
            '</desc>',
            '<image id="original-background" x="0" y="0" width="800" '
            'height="1800" href="data:image/jpeg;base64,' + encoded + '"/>',
            '<g id="lower-area-overlay">',
        ]
        self.text_bounds = []
        self.overlay_line_bounds = []

    def text(self, value, x, y, size, font="CN", colour=INK, tracking=0):
        super().text(value, x, y, size, font, colour, tracking)
        if self.text_bounds[-1]["top"] < PROTECTED_BOTTOM:
            raise ValueError("Text intrudes into the protected upper area")

    def centered(self, value, center_x, y, size,
                 font="OverlayHand", tracking=0):
        width = pdfmetrics.stringWidth(value, font, size)
        width += max(0, len(value) - 1) * tracking
        self.text(value, center_x - width / 2, y,
                  size, font, INK, tracking)

    def overlay_line(self, x, y1, y2, width):
        if min(y1, y2) - width / 2 < PROTECTED_BOTTOM:
            raise ValueError("Line intrudes into the protected upper area")
        self.line(x, y1, x, y2, INK, width)
        self.overlay_line_bounds.append({"x": x, "top": min(y1, y2),
                                         "bottom": max(y1, y2)})

    def save(self):
        self.pdf.showPage()
        self.pdf.save()
        self.parts += ["</g>", "</svg>"]
        svg = "\n".join(self.parts)
        (ROOT / f"{STEM}.svg").write_text(svg, encoding="utf-8")
        (ROOT / f"{STEM}.html").write_text(
            '<!doctype html><html lang="zh-CN"><head>'
            '<meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1">'
            '<title>Gesture Bridge</title><style>'
            '*{box-sizing:border-box}body{margin:0;background:#e8c571}'
            'main{width:min(100%,800px);margin:0 auto}'
            'svg{display:block;width:100%;height:auto}'
            '@page{size:800mm 1800mm;margin:0}'
            '@media print{main{width:800mm;margin:0}'
            'svg{width:800mm;height:1800mm}}'
            '</style></head><body><main>' + svg
            + '</main></body></html>', encoding="utf-8",
        )
        outside = [
            box for box in self.text_bounds
            if box["x"] < 0 or box["right"] > WIDTH
            or box["top"] < 0 or box["bottom"] > HEIGHT
        ]
        report = {
            "project_name": "Gesture Bridge",
            "dimensions_mm": [800, 1800],
            "background_pixels": [800, 1800],
            "background_sha256": hashlib.sha256(
                BACKGROUND.read_bytes()).hexdigest(),
            "background_handling": "Unmodified original JPEG, embedded",
            "protected_region": [0, 0, 800, PROTECTED_BOTTOM],
            "text_outside_page": outside,
            "overlay_text_bounds": self.text_bounds,
            "overlay_line_bounds": self.overlay_line_bounds,
            "print_note": "Background is raster; new text and lines are vector",
        }
        (ROOT / f"{STEM}-check.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if outside:
            raise ValueError(outside)


def audio_levels():
    path = ROOT.parent.parent / "headvoice" / "audio" / "AA.pcm"
    samples = [item[0] for item in struct.iter_unpack("<h", path.read_bytes())]
    threshold = max(abs(value) for value in samples) * .02
    active = [i for i, value in enumerate(samples) if abs(value) > threshold]
    samples = samples[max(0, active[0] - 128):active[-1] + 129]
    levels = []
    for i in range(22):
        window = samples[len(samples) * i // 22:len(samples) * (i + 1) // 22]
        levels.append(math.sqrt(sum(v * v for v in window) / len(window)))
    peak = max(levels) or 1
    return [3 + 16 * math.sqrt(level / peak) for level in levels]


def main():
    p = ReferencePoster()
    p.centered("手势识别", 260, 1088, 28)
    p.centered("GESTURE", 260, 1118, 10.5, "Latin", tracking=1.2)

    p.centered("手势，", 520, 1186, 54)
    p.centered("变成声音。", 520, 1263, 54)
    p.centered("GESTURE TO VOICE", 520, 1310,
               13, "Latin", tracking=.9)
    p.centered("语音示例", 520, 1365, 14)
    p.centered("“我想喝水。”", 520, 1413, 31)
    for i, amplitude in enumerate(audio_levels()):
        x = 415 + i * 10
        p.overlay_line(x, 1468 - amplitude, 1468 + amplitude, 2.1)

    p.centered("手势识别 · 确认表达 · 语音播报", 520, 1646, 16)
    p.save()


if __name__ == "__main__":
    main()
