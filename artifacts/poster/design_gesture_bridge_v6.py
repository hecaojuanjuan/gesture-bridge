"""Draw the user-directed charcoal and ochre, hand-drawn poster."""

import json
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from design_gesture_bridge_v4 import FONT_FILES, MM, Poster
from design_gesture_bridge_v5 import CHAINS, LANDMARKS

ROOT = Path(__file__).resolve().parent
STEM = "gesture-bridge-poster-v6"
WIDTH, HEIGHT = 800, 1800
YELLOW = "#EDC871"
CHARCOAL = "#494B48"
WHITE = "#F3F1EB"
BLUE = "#83AFC1"
ORANGE = "#EFA96F"
INK = "#454A43"

FONT_FILES["Marker"] = ("segoeprb.ttf", "Segoe Print", "700")
FONT_FILES["CNHand"] = ("simkai.ttf", "KaiTi", "400")
for name in ["Marker", "CNHand"]:
    filename, _, _ = FONT_FILES[name]
    pdfmetrics.registerFont(TTFont(name, f"C:/Windows/Fonts/{filename}"))


class SketchPoster(Poster):
    """Share the vector primitives and retain an actual-size print export."""

    def __init__(self):
        self.pdf = canvas.Canvas(
            str(ROOT / f"{STEM}-80x180cm.pdf"),
            pagesize=(WIDTH * MM, HEIGHT * MM),
            pageCompression=1,
        )
        self.pdf.setTitle("Gesture Bridge")
        self.pdf.setAuthor("Gesture Bridge")
        self.pdf.setSubject("A gesture becomes a voice; concept poster")
        self.pdf.scale(MM, MM)
        self.parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="800mm" '
            'height="1800mm" viewBox="0 0 800 1800" role="img" '
            'aria-labelledby="title description">',
            '<title id="title">Gesture Bridge</title>',
            '<desc id="description">Hand-lettered white typography, a '
            'faceless figure making a gesture, a device concept, and blue '
            'and orange speech shapes on charcoal and warm ochre fields.'
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
            '*{box-sizing:border-box}body{margin:0;background:#d6c18d}'
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
            "direction": "User reference: charcoal / ochre / hand-drawn",
            "landmark_count": len(LANDMARKS),
            "text_outside_page": outside,
            "artwork_status": "Product concept; no detection result claimed",
        }
        (ROOT / f"{STEM}-check.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if outside:
            raise ValueError(outside)


def background(poster):
    poster.rect(0, 0, WIDTH, HEIGHT, YELLOW)
    poster.path([
        ("M", 0, 0), ("L", 800, 0), ("L", 800, 187),
        ("C", 743, 283, 629, 412, 515, 505),
        ("C", 413, 589, 365, 626, 368, 691),
        ("C", 323, 703, 310, 677, 268, 687),
        ("C", 186, 704, 127, 741, 78, 802),
        ("C", 41, 846, 17, 883, 0, 915), ("Z",),
    ], fill=CHARCOAL)


def person(poster):
    # The head, neck, and shoulders are unbroken, deliberately simple curves.
    poster.path([
        ("M", 194, 550),
        ("C", 146, 518, 128, 464, 138, 411),
        ("C", 146, 365, 190, 338, 237, 342),
        ("C", 297, 346, 337, 390, 341, 447),
        ("C", 345, 506, 315, 554, 281, 566),
        ("C", 250, 575, 220, 556, 210, 543),
        ("M", 194, 550),
        ("C", 205, 576, 200, 611, 183, 636),
        ("C", 156, 661, 104, 679, 79, 700),
        ("C", 61, 722, 55, 786, 51, 846),
        ("M", 281, 566),
        ("C", 275, 589, 282, 613, 308, 627),
        ("C", 334, 643, 352, 665, 367, 699),
    ], stroke=WHITE, width=3.5)

    # A raised hand keeps the previous gesture-recognition concept visible.
    hand = [
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
        ("C", 235, 632, 216, 658, 207, 703),
    ]
    transformed = []
    for op, *values in hand:
        out = [op]
        for i in range(0, len(values), 2):
            out.extend((363 + values[i] * .26,
                        341 + values[i + 1] * .26))
        transformed.append(tuple(out))
    poster.path(transformed, stroke=WHITE, width=1.7)
    for chain in CHAINS:
        points = [
            (363 + LANDMARKS[i][0] * .26,
             341 + LANDMARKS[i][1] * .26)
            for i in chain
        ]
        poster.path([("M", *points[0])]
                    + [("L", *point) for point in points[1:]],
                    stroke=WHITE, width=.38)
    for point in LANDMARKS:
        poster.circle(363 + point[0] * .26, 341 + point[1] * .26,
                      .9, fill=WHITE)
    poster.path([
        ("M", 389, 523),
        ("C", 384, 562, 369, 607, 344, 626),
        ("L", 328, 642),
        ("M", 417, 524),
        ("C", 435, 568, 432, 614, 399, 655),
        ("C", 389, 675, 377, 690, 366, 699),
    ], stroke=WHITE, width=2.3)


def device_patch(poster):
    poster.path([
        ("M", 234, 783),
        ("C", 263, 740, 308, 713, 365, 701),
        ("C", 405, 691, 439, 707, 480, 703),
        ("C", 526, 697, 559, 703, 603, 709),
        ("C", 628, 712, 648, 725, 650, 752),
        ("L", 646, 892),
        ("C", 647, 922, 632, 937, 606, 945),
        ("C", 568, 955, 543, 971, 496, 970),
        ("C", 448, 975, 402, 965, 364, 963),
        ("C", 325, 960, 284, 966, 246, 955),
        ("C", 248, 907, 236, 870, 239, 835),
        ("C", 236, 818, 235, 796, 234, 783), ("Z",),
    ], fill=WHITE)

    # A restrained line drawing supplies the concept image inside the patch.
    poster.path([
        ("M", 315, 850), ("L", 459, 813), ("L", 593, 858),
        ("L", 451, 900), ("L", 315, 850),
        ("L", 315, 910), ("L", 451, 954), ("L", 593, 912),
        ("L", 593, 858), ("M", 451, 900), ("L", 451, 954),
    ], stroke=INK, width=1.9)
    poster.path([
        ("M", 344, 850), ("L", 460, 822),
        ("L", 565, 858), ("L", 451, 888), ("Z",),
    ], fill="#DDDCD3", stroke=INK, width=.9)
    poster.path([
        ("M", 453, 851), ("L", 467, 846), ("L", 481, 852),
        ("L", 467, 857), ("Z",),
    ], fill=INK)
    poster.line(467, 848, 467, 802, INK, 3)
    poster.path([
        ("M", 430, 778), ("L", 430, 804),
        ("L", 504, 804), ("L", 504, 778),
    ], stroke=INK, width=1.4)
    poster.path([
        ("M", 437, 734), ("L", 487, 729),
        ("L", 496, 787), ("L", 443, 793), ("Z",),
    ], fill=INK)
    poster.circle(467, 762, 17, stroke=WHITE, width=1.3)
    poster.circle(467, 762, 9, stroke=WHITE, width=.7)
    poster.circle(467, 762, 2.4, fill=WHITE)
    for row in range(3):
        for col in range(7):
            poster.circle(478 + col * 6, 913 - col * 1.8 + row * 7,
                          1.3, fill=INK)
    poster.circle(565, 898, 3, fill=BLUE)
    poster.text("设备概念", 336, 937, 10, "CNHand", INK)


def speech_shapes(poster):
    poster.path([
        ("M", 287, 980),
        ("C", 286, 998, 293, 1007, 318, 1013),
        ("C", 363, 1026, 386, 1056, 392, 1084),
        ("C", 406, 1122, 385, 1152, 346, 1168),
        ("C", 304, 1188, 251, 1183, 194, 1172),
        ("C", 150, 1160, 124, 1128, 128, 1087),
        ("C", 133, 1047, 165, 1014, 214, 1008),
        ("C", 241, 1007, 266, 994, 279, 978),
        ("C", 283, 972, 288, 974, 287, 980), ("Z",),
    ], fill=BLUE)
    poster.path([
        ("M", 438, 1055),
        ("C", 443, 1021, 447, 1007, 459, 1015),
        ("C", 473, 1016, 486, 1038, 491, 1055),
        ("C", 533, 1075, 599, 1078, 643, 1110),
        ("C", 712, 1154, 763, 1203, 774, 1266),
        ("C", 791, 1325, 774, 1391, 745, 1443),
        ("C", 718, 1495, 664, 1525, 595, 1544),
        ("C", 528, 1566, 466, 1570, 403, 1554),
        ("C", 344, 1542, 312, 1511, 289, 1472),
        ("C", 260, 1434, 252, 1387, 257, 1337),
        ("C", 252, 1288, 274, 1231, 298, 1185),
        ("C", 328, 1134, 373, 1097, 421, 1074),
        ("C", 432, 1069, 436, 1062, 438, 1055), ("Z",),
    ], fill=ORANGE)

    poster.text("我想喝水。", 164, 1099, 28, "CNHand", INK)
    poster.text("让动作，", 353, 1236, 53, "CNHand", INK)
    poster.text("拥有声音。", 333, 1314, 53, "CNHand", INK)
    poster.text("From gesture", 365, 1403, 17, "Marker", INK)
    poster.text("to understanding.", 365, 1437, 17, "Marker", INK)


def main():
    p = SketchPoster()
    background(p)
    person(p)
    p.text("Gesture", 44, 182, 125, "Marker", WHITE, tracking=1.3)
    p.text("Bridge", 184, 319, 130, "Marker", WHITE, tracking=2)
    device_patch(p)
    speech_shapes(p)
    p.text("动作识别 · 本人确认 · 语音表达", 55, 1691,
           16, "CNHand", INK)
    p.text("完整产品设计 / 部分功能开发验证中", 55, 1752,
           10, "CNHand", INK)
    p.save()


if __name__ == "__main__":
    main()
