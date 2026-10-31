"""Complete the supplied fixed template with device and expression content."""

import base64
import hashlib
import json
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from design_gesture_bridge_v4 import FONT_FILES, MM, Poster
from design_gesture_bridge_v7 import HAND_OUTLINE

ROOT = Path(__file__).resolve().parent
STEM = "gesture-bridge-poster-v9"
BACKGROUND = ROOT / f"{STEM}-background.jpg"
WIDTH, HEIGHT = 800, 1800
INK = "#454A46"
DEVICE_WHITE = "#F2F1E9"
FONT_FILES["TemplateHand"] = ("simkai.ttf", "KaiTi", "400")
pdfmetrics.registerFont(TTFont("TemplateHand", "C:/Windows/Fonts/simkai.ttf"))


class TemplatePoster(Poster):
    """Preserve the background asset and export editable foreground content."""

    def __init__(self):
        self.pdf = canvas.Canvas(
            str(ROOT / f"{STEM}-80x180cm.pdf"),
            pagesize=(WIDTH * MM, HEIGHT * MM),
            pageCompression=1,
        )
        self.pdf.setTitle("Gesture Bridge")
        self.pdf.setAuthor("Gesture Bridge")
        self.pdf.setSubject(
            "Gesture input, reviewed expression, spoken output")
        self.pdf.scale(MM, MM)
        self.pdf.drawImage(str(BACKGROUND), 0, 0, width=WIDTH, height=HEIGHT)
        encoded = base64.b64encode(BACKGROUND.read_bytes()).decode("ascii")
        self.parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="800mm" '
            'height="1800mm" viewBox="0 0 800 1800" role="img" '
            'aria-labelledby="title description">',
            '<title id="title">Gesture Bridge</title>',
            '<desc id="description">The supplied template is unchanged. '
            'A device concept appears above the speech shapes. The orange '
            'shape contains the four-step gesture-to-speech process; '
            'the blue shape describes easier interaction; the pale yellow '
            'shape describes family-assisted configuration.</desc>',
            '<image id="original-background" x="0" y="0" width="800" '
            'height="1800" href="data:image/jpeg;base64,' + encoded + '"/>',
            '<g id="editable-content">',
        ]
        self.text_bounds = []
        self.regions = {}

    def centered(self, value, center_x, y, size,
                 font="TemplateHand", tracking=0):
        width = pdfmetrics.stringWidth(value, font, size)
        width += max(0, len(value) - 1) * tracking
        self.text(value, center_x - width / 2, y,
                  size, font, INK, tracking)

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
        protected_text = [
            box for box in self.text_bounds if box["top"] < 700
            or (box["x"] < 350 and box["top"] < 950)
        ]
        report = {
            "project_name": "Gesture Bridge",
            "dimensions_mm": [800, 1800],
            "background_pixels": [800, 1800],
            "background_sha256": hashlib.sha256(
                BACKGROUND.read_bytes()).hexdigest(),
            "background_handling": "Unmodified supplied JPEG, embedded",
            "protected_regions": [[0, 0, 800, 700], [0, 0, 350, 950]],
            "text_outside_page": outside,
            "text_in_protected_regions": protected_text,
            "text_bounds": self.text_bounds,
            "content_regions": self.regions,
            "device_image": "Existing project enclosure concept, vector",
            "print_note": "Raster template; editable vector foreground",
        }
        (ROOT / f"{STEM}-check.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if outside or protected_text:
            raise ValueError({"outside": outside, "protected": protected_text})


def device_image(poster):
    """Place the existing enclosure concept in the central yellow area."""
    start = len(poster.parts)
    poster.parts.append('<g id="device-concept">')

    def pt(x, y):
        return x + 55, y - 6

    def path(commands, fill=None, stroke=INK, width=1.5):
        translated = []
        for op, *values in commands:
            out = [op]
            for i in range(0, len(values), 2):
                out.extend(pt(values[i], values[i + 1]))
            translated.append(tuple(out))
        poster.path(translated, fill, stroke, width)

    def polygon(points, fill):
        path([("M", *points[0])]
             + [("L", *point) for point in points[1:]] + [("Z",)],
             fill=fill)

    # Opaque case planes retain the project's low desktop enclosure form.
    polygon([(315, 850), (451, 900), (451, 954), (315, 910)], DEVICE_WHITE)
    polygon([(451, 900), (593, 858), (593, 912), (451, 954)], "#DDDFD7")
    polygon([(315, 850), (459, 813), (593, 858), (451, 900)], DEVICE_WHITE)
    polygon([(344, 850), (460, 822), (565, 858), (451, 888)], "#AEB3AA")
    polygon([(453, 851), (467, 846), (481, 852), (467, 857)], INK)
    path([("M", 467, 848), ("L", 467, 802)], width=3)
    path([("M", 430, 778), ("L", 430, 804),
          ("L", 504, 804), ("L", 504, 778)])
    polygon([(437, 734), (487, 729), (496, 787), (443, 793)], INK)
    poster.circle(*pt(467, 762), 17, stroke=DEVICE_WHITE, width=1.3)
    poster.circle(*pt(467, 762), 9, stroke=DEVICE_WHITE, width=.7)
    poster.circle(*pt(467, 762), 2.4, fill=DEVICE_WHITE)
    for row in range(3):
        for col in range(7):
            poster.circle(*pt(478 + col * 6, 913 - col * 1.8 + row * 7),
                          1.3, fill=INK)
    poster.circle(*pt(565, 898), 3, fill="#83AFC1")
    poster.parts.append("</g>")
    drawing = "\n".join(poster.parts[start:])
    (ROOT / "gesture-bridge-device-concept.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="282" height="229" '
        'viewBox="368 721 282 229">' + drawing + '</svg>', encoding="utf-8"
    )
    poster.centered("设备示意", 515, 974, 11)
    poster.regions["device"] = [370, 723, 648, 976]


def hand_icon(poster, x, y):
    commands = []
    for op, *values in HAND_OUTLINE:
        out = [op]
        for i in range(0, len(values), 2):
            out.extend((x - 11 + values[i] * .065,
                        y - 32 + values[i + 1] * .065))
        commands.append(tuple(out))
    poster.path(commands, stroke=INK, width=1.1)


def speech_icon(poster, x, y):
    poster.path([
        ("M", x - 13, y - 12), ("L", x + 13, y - 12),
        ("L", x + 13, y + 7), ("L", x - 4, y + 7),
        ("L", x - 13, y + 14), ("Z",),
    ], stroke=INK, width=1.5)


def confirm_icon(poster, x, y):
    poster.circle(x, y, 14, stroke=INK, width=1.5)
    poster.path([("M", x - 7, y), ("L", x - 2, y + 5),
                 ("L", x + 7, y - 5)], stroke=INK, width=1.8)


def speaker_icon(poster, x, y):
    poster.path([
        ("M", x - 14, y - 5), ("L", x - 8, y - 5),
        ("L", x + 1, y - 13), ("L", x + 1, y + 13),
        ("L", x - 8, y + 5), ("L", x - 14, y + 5), ("Z",),
        ("M", x + 7, y - 7),
        ("C", x + 12, y - 3, x + 12, y + 3, x + 7, y + 7),
        ("M", x + 12, y - 12),
        ("C", x + 21, y - 5, x + 21, y + 5, x + 12, y + 12),
    ], stroke=INK, width=1.5)


def process_flow(poster):
    poster.parts.append('<g id="gesture-to-speech-flow">')
    poster.centered("从手势到语音", 525, 1139, 30)
    steps = [
        (1207, "做出手势组合", "选择想说的话", hand_icon),
        (1290, "呈现候选句", "“我想喝水。”", speech_icon),
        (1373, "本人再次确认", "也可以取消", confirm_icon),
        (1456, "原句语音播报", "表达不被改写", speaker_icon),
    ]
    for i, (y, title, subtitle, icon) in enumerate(steps):
        icon(poster, 434, y - 7)
        poster.text(title, 474, y, 22, "CN", INK)
        poster.text(subtitle, 474, y + 26, 13, "CN", INK)
        if i < len(steps) - 1:
            poster.line(434, y + 15, 434, y + 54, INK, .65)
            poster.arrow(434, y + 54, 90, INK, 4)
    poster.parts.append("</g>")
    poster.regions["orange_flow"] = [418, 1109, 610, 1487]


def support_copy(poster):
    poster.parts.append('<g id="blue-bubble-content">')
    poster.centered("无需精细操作", 260, 1067, 24)
    poster.centered("降低表达门槛", 260, 1106, 24)
    poster.parts.append("</g>")
    poster.regions["blue"] = [188, 1046, 332, 1112]

    poster.parts.append('<g id="family-bubble-content">')
    poster.centered("家人协助", 136, 1268, 25)
    poster.centered("一起定义手势", 136, 1321, 20)
    poster.centered("与表达内容", 136, 1357, 20)
    poster.centered("由使用者确认", 136, 1410, 13.5)
    poster.parts.append("</g>")
    poster.regions["pale_yellow"] = [76, 1245, 196, 1414]

    poster.centered("让表达被听见", 525, 1635, 22, "CNB")
    poster.regions["closing_line"] = [459, 1614, 591, 1641]


def main():
    p = TemplatePoster()
    device_image(p)
    process_flow(p)
    support_copy(p)
    p.save()


if __name__ == "__main__":
    main()
