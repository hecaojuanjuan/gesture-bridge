"""Draw an original vector poster and an editable SVG from the same geometry."""

from html import escape
import json
import math
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 800, 1800
MM = 72 / 25.4
PAPER = "#F5F3EC"
INK = "#171816"
GREY = "#777A73"
PALE = "#D4D5CC"
ACCENT = "#D9462A"

FONT_FILES = {
    "Latin": ("arial.ttf", "Arial", "400"),
    "Heavy": ("ariblk.ttf", "Arial Black", "900"),
    "CN": ("msyh.ttc", "Microsoft YaHei", "400"),
    "CNB": ("msyhbd.ttc", "Microsoft YaHei", "700"),
}
for name, (filename, _, _) in FONT_FILES.items():
    pdfmetrics.registerFont(TTFont(name, str(Path("C:/Windows/Fonts") / filename)))


class Poster:
    def __init__(self):
        self.pdf = canvas.Canvas(
            str(ROOT / "gesture-bridge-poster-v4-80x180cm.pdf"),
            pagesize=(WIDTH * MM, HEIGHT * MM),
            pageCompression=1,
        )
        self.pdf.setTitle("gesture bridge - 80 x 180 cm")
        self.pdf.setAuthor("Gesture Bridge")
        self.pdf.setSubject("Head posture to confirmed speech; product concept")
        self.pdf.scale(MM, MM)
        self.parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="800mm" '
            'height="1800mm" viewBox="0 0 800 1800" '
            'role="img" aria-labelledby="title description">',
            '<title id="title">gesture bridge</title>',
            '<desc id="description">头部姿态经设备识别为动作编码，形成候选句，'
            '由使用者再次确认后播报。黑白与朱红色的矢量海报。</desc>',
        ]
        self.text_bounds = []

    def style(self, fill=None, stroke=None, width=1):
        if fill:
            self.pdf.setFillColor(HexColor(fill))
        if stroke:
            self.pdf.setStrokeColor(HexColor(stroke))
        self.pdf.setLineWidth(width)
        self.pdf.setLineCap(1)
        self.pdf.setLineJoin(1)
        return (
            f'fill="{fill or "none"}" stroke="{stroke or "none"}" '
            f'stroke-width="{width}" stroke-linecap="round" '
            'stroke-linejoin="round"'
        )

    def rect(self, x, y, w, h, fill=None, stroke=None, width=1):
        style = self.style(fill, stroke, width)
        self.pdf.rect(x, HEIGHT - y - h, w, h, fill=bool(fill), stroke=bool(stroke))
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" {style}/>'
        )

    def circle(self, x, y, r, fill=None, stroke=None, width=1):
        style = self.style(fill, stroke, width)
        self.pdf.circle(x, HEIGHT - y, r, fill=bool(fill), stroke=bool(stroke))
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" {style}/>')

    def path(self, commands, fill=None, stroke=None, width=1):
        style = self.style(fill, stroke, width)
        p = self.pdf.beginPath()
        svg = []
        for command in commands:
            op, *v = command
            svg.append(op + " ".join(f"{value:.3f}" for value in v))
            if op == "M":
                p.moveTo(v[0], HEIGHT - v[1])
            elif op == "L":
                p.lineTo(v[0], HEIGHT - v[1])
            elif op == "C":
                p.curveTo(v[0], HEIGHT - v[1], v[2], HEIGHT - v[3],
                          v[4], HEIGHT - v[5])
            elif op == "Z":
                p.close()
        self.pdf.drawPath(p, fill=bool(fill), stroke=bool(stroke))
        self.parts.append(f'<path d="{" ".join(svg)}" {style}/>')

    def line(self, x1, y1, x2, y2, colour=INK, width=1):
        self.path([("M", x1, y1), ("L", x2, y2)], stroke=colour, width=width)

    def polygon(self, points, fill=None, stroke=None, width=1):
        self.path([("M", *points[0])]
                  + [("L", *point) for point in points[1:]] + [("Z",)],
                  fill, stroke, width)

    def text(self, value, x, y, size, font="CN", colour=INK, tracking=0):
        self.pdf.setFillColor(HexColor(colour))
        t = self.pdf.beginText(x, HEIGHT - y)
        t.setFont(font, size)
        t.setCharSpace(tracking)
        t.textOut(value)
        self.pdf.drawText(t)
        _, family, weight = FONT_FILES[font]
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{family}" '
            f'font-weight="{weight}" font-size="{size}" '
            f'letter-spacing="{tracking}" fill="{colour}">'
            f'{escape(value)}</text>'
        )
        tw = pdfmetrics.stringWidth(value, font, size)
        tw += max(0, len(value) - 1) * tracking
        ascent, descent = pdfmetrics.getAscentDescent(font, size)
        self.text_bounds.append({"text": value, "x": x, "right": x + tw,
                                 "top": y - ascent, "bottom": y - descent})

    def fitted(self, value, x, y, width, font="Heavy", colour=INK, tracking=-5):
        normal = pdfmetrics.stringWidth(value, font, 1)
        size = (width - (len(value) - 1) * tracking) / normal
        self.text(value, x, y, size, font, colour, tracking)

    def arrow(self, x, y, angle=0, colour=ACCENT, size=9):
        rad = math.radians(angle)
        points = [(0, 0), (-size, -.6 * size), (-size, .6 * size)]
        self.polygon([
            (x + px * math.cos(rad) - py * math.sin(rad),
             y + px * math.sin(rad) + py * math.cos(rad))
            for px, py in points
        ], fill=colour)

    def save(self):
        self.pdf.showPage()
        self.pdf.save()
        self.parts.append("</svg>")
        (ROOT / "gesture-bridge-poster-v4.svg").write_text(
            "\n".join(self.parts), encoding="utf-8"
        )
        outside = [b for b in self.text_bounds if b["x"] < 0
                   or b["right"] > WIDTH or b["top"] < 0
                   or b["bottom"] > HEIGHT]
        report = {"size_cm": [80, 180], "page_count": 1,
                  "method": "Original vector layout; embedded fonts in PDF",
                  "text_outside_page": outside}
        (ROOT / "gesture-bridge-poster-v4-check.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if outside:
            raise ValueError(outside)


def transform(commands, cx, cy, angle):
    rad = math.radians(angle)
    cos, sin = math.cos(rad), math.sin(rad)
    result = []
    for op, *values in commands:
        out = [op]
        for i in range(0, len(values), 2):
            x, y = values[i:i + 2]
            out += [cx + x * cos - y * sin, cy + x * sin + y * cos]
        result.append(tuple(out))
    return result


def transformed_point(x, y, cx=164, cy=651, angle=12):
    rad = math.radians(angle)
    return cx + x * math.cos(rad) - y * math.sin(rad), \
        cy + x * math.sin(rad) + y * math.cos(rad)


def head(poster):
    contour = [
        ("M", -44, 92), ("L", -44, 62),
        ("C", -78, 40, -88, 10, -87, -26),
        ("C", -87, -77, -56, -113, -14, -113),
        ("C", 24, -113, 45, -86, 46, -50),
        ("L", 59, -27), ("L", 44, -19),
        ("C", 43, 11, 28, 32, 8, 41), ("L", 7, 77),
    ]
    poster.path(transform(contour, 164, 651, -12), stroke=PALE, width=2)
    poster.path(transform(contour, 164, 651, 12), stroke=INK, width=2.7)
    shoulders = [("M", -44, 92), ("C", -74, 97, -101, 112, -113, 143),
                 ("M", 7, 77), ("C", 31, 86, 62, 99, 75, 125)]
    poster.path(transform(shoulders, 164, 651, 12), stroke=INK, width=2.7)
    landmarks = [(24, -48), (44, -19), (-39, -39)]
    for a, b in zip(landmarks, landmarks[1:]):
        poster.line(*transformed_point(*a), *transformed_point(*b),
                    colour=ACCENT, width=.9)
    for point in landmarks:
        poster.circle(*transformed_point(*point), 3.5, fill=ACCENT)
    poster.path([("M", 98, 521), ("C", 145, 496, 200, 506, 225, 538)],
                stroke=GREY, width=1)
    poster.arrow(225, 538, 45, GREY, 7)
    poster.text("动作 B / 示意", 57, 810, 12, colour=GREY)
    poster.text("轻轻侧倾，再回正。", 55, 849, 21, font="CNB")


def device(poster):
    # Case geometry, expressed as three explicit solid planes.
    poster.polygon([(350, 870), (513, 939), (513, 1020), (350, 951)],
                   PAPER, INK, 1.8)
    poster.polygon([(513, 939), (755, 869), (755, 950), (513, 1020)],
                   "#E5E5DD", INK, 1.8)
    poster.polygon([(350, 870), (591, 804), (755, 869), (513, 939)],
                   PAPER, INK, 1.8)
    poster.polygon([(394, 873), (589, 820), (710, 870), (513, 924)],
                   INK, INK, 1)
    for x, y in [(367, 870), (591, 813), (735, 870), (513, 931)]:
        poster.circle(x, y, 2.1, stroke=GREY, width=.8)
    # Exposed gimbal base, shaft, and two-arm bracket.
    poster.polygon([(536, 861), (583, 847), (620, 862), (574, 877)],
                   "#8D9088", INK, 1)
    poster.rect(566, 825, 18, 36, PAPER, INK, 1.4)
    poster.path([("M", 526, 786), ("L", 526, 823),
                 ("L", 617, 823), ("L", 617, 781)], stroke=PAPER, width=7)
    poster.path([("M", 526, 786), ("L", 526, 823),
                 ("L", 617, 823), ("L", 617, 781)], stroke=INK, width=1.5)
    poster.polygon([(536, 716), (603, 698), (635, 712), (568, 731)],
                   "#777A73", INK, 1)
    poster.polygon([(603, 698), (635, 712), (635, 792), (603, 780)],
                   "#A2A49B", INK, 1)
    poster.polygon([(536, 716), (603, 698), (603, 780), (536, 799)],
                   INK, INK, 1.6)
    poster.circle(570, 751, 22, fill=INK, stroke=PAPER, width=1.5)
    poster.circle(570, 751, 14, fill="#4D5149", stroke=PAPER, width=.6)
    poster.circle(570, 751, 5.8, fill=PAPER)
    poster.circle(526, 790, 3, fill=PAPER, stroke=INK, width=1)
    poster.circle(618, 790, 3, fill=PAPER, stroke=INK, width=1)
    # Small speaker perforations follow the plane of the enclosure.
    for row in range(5):
        for col in range(8):
            x = 573 + col * 7.6
            y = 938 - col * 2.2 + row * 6.7
            poster.circle(x, y, 1.35, fill=INK)
    poster.circle(710, 925, 3.3, fill=ACCENT)
    poster.line(680, 1001, 724, 1028, GREY, .7)
    poster.text("设备概念示意", 619, 1051, 12, colour=GREY)


def main():
    p = Poster()
    p.rect(0, 0, WIDTH, HEIGHT, PAPER)

    # The wordmark is the first distance-reading layer.
    p.circle(741, 41, 5, fill=ACCENT)
    p.fitted("gesture", 45, 150, 600, tracking=-7)
    p.fitted("bridge", 45, 325, 600, tracking=-7)
    p.text("让动作，拥有声音。", 55, 407, 31, "CNB")
    p.text("头部姿态辅助沟通设备", 56, 440, 15, colour=GREY)
    p.text("MOTION", 659, 391, 10, "Latin", tracking=1.4)
    p.text("TO MEANING", 630, 413, 10, "Latin", tracking=1.2)
    p.line(55, 467, 745, 467, INK, .8)

    # One drawn figure, one drawn device, one continuous signal path.
    p.text("01", 55, 499, 12, "Latin")
    p.text("姿态输入", 87, 499, 13, "CNB")
    p.text("02", 394, 665, 12, "Latin")
    p.text("设备转换", 426, 665, 13, "CNB")
    head(p)

    eye = transformed_point(24, -48)
    p.path([("M", *eye), ("L", 286, eye[1]),
            ("C", 375, eye[1], 375, 751, 498, 751), ("L", 533, 751)],
           stroke=ACCENT, width=2)
    p.arrow(533, 751, 0, size=8)
    p.text("B + B", 329, 567, 29, "Latin", ACCENT, tracking=1.6)
    p.text("动作组合 / BB", 330, 594, 11, colour=GREY)

    # Output path sits behind the hardware and terminates at new confirmation.
    p.path([("M", 635, 953), ("L", 697, 982),
            ("C", 745, 1005, 723, 1081, 707, 1121),
            ("L", 677, 1189)], stroke=ACCENT, width=2)
    p.arrow(677, 1189, 114, size=8)
    device(p)
    p.text("候选句 / 我想自己来。", 384, 1100, 14)
    p.line(565, 1095, 715, 1095, GREY, .6)
    p.text("用新动作确认后", 574, 1221, 13, colour=ACCENT)
    p.path([("M", 696, 1158), ("L", 704, 1167), ("L", 718, 1149)],
           stroke=ACCENT, width=2.4)

    # The spoken sentence is the main visual payoff, not a secondary label.
    p.text("03", 55, 1175, 12, "Latin")
    p.text("语言输出", 87, 1175, 13, "CNB")
    p.text("我想", 45, 1314, 126, "CNB", tracking=-8)
    p.text("自己来。", 45, 1460, 140, "CNB", ACCENT, tracking=-9)

    stages = ["姿态识别", "动作编码", "候选呈现", "本人确认", "原句播报"]
    for i, stage in enumerate(stages):
        x = 55 + 141 * i
        p.text(stage, x, 1518, 16, "CNB")
        if i < len(stages) - 1:
            p.line(x + 82, 1512, x + 115, 1512, GREY, .8)
            p.arrow(x + 115, 1512, 0, GREY, 4.5)

    p.line(55, 1564, 745, 1564, INK, .8)
    columns = [
        (55, "表达由自己定义", ["整句自定义，或通过扫描", "选句与有限词库拼句。"]),
        (293, "内容由本人确认", ["动作组合形成候选，", "再用一次新动作确认。"]),
        (531, "输入适应每个人", ["个人校准与纠正学习，", "保留单动作扫描路径。"]),
    ]
    for x, heading, lines in columns:
        p.text(heading, x, 1610, 18.5, "CNB")
        for j, line in enumerate(lines):
            p.text(line, x, 1648 + j * 25, 13, colour=GREY)
    p.text("为言语表达受限、仍能完成可辨识头部动作的人设计。",
           55, 1734, 13)
    p.line(55, 1751, 745, 1751, PALE, .6)
    p.text("完整产品设计 / 部分功能开发验证中", 55, 1775, 10.5, colour=GREY)
    p.text("GESTURE BRIDGE / 2026", 575, 1775, 9.5, "Latin", tracking=.45)
    p.save()


if __name__ == "__main__":
    main()
