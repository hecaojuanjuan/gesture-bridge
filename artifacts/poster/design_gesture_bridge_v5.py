"""Build the Gesture Bridge editorial poster using the existing vector stack."""

import json
import math
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from design_gesture_bridge_v4 import FONT_FILES, MM, Poster

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 800, 1800
PAPER = "#F0EEE8"
INK = "#252525"
GRAY = "#A4A6A3"
MID_GRAY = "#767A76"
HAND_GRAY = "#BFC1BA"
TEAL = "#137C83"
ORANGE = "#F4A574"
CORAL = "#DD6F60"
STEM = "gesture-bridge-poster-v5"

FONT_FILES["Grotesk"] = ("arialbd.ttf", "Arial", "700")
pdfmetrics.registerFont(TTFont("Grotesk", "C:/Windows/Fonts/arialbd.ttf"))

# The first point is the wrist. Each following chain follows real joints.
LANDMARKS = [
    (135, 674),
    (207, 619), (246, 576), (281, 541), (314, 510),
    (196, 519), (208, 435), (212, 377), (211, 328),
    (143, 506), (142, 410), (138, 345), (133, 294),
    (91, 520), (80, 437), (75, 385), (68, 340),
    (44, 550), (24, 487), (12, 447), (2, 410),
]
FINGERS = [
    ([1, 2, 3, 4], [25, 22, 18, 15]),
    ([5, 6, 7, 8], [18, 17, 15, 13]),
    ([9, 10, 11, 12], [20, 18, 16, 14]),
    ([13, 14, 15, 16], [19, 17, 15, 13]),
    ([17, 18, 19, 20], [16, 15, 13, 11]),
]
CHAINS = [
    [0, 1, 2, 3, 4], [0, 5, 6, 7, 8],
    [5, 9, 10, 11, 12], [9, 13, 14, 15, 16],
    [13, 17, 18, 19, 20], [0, 17],
]
PALM = [
    (82, 739), (61, 675), (30, 606), (24, 557), (38, 533),
    (60, 519), (98, 500), (151, 493), (196, 513), (215, 546),
    (223, 585), (208, 639), (192, 688), (187, 739),
    (-70, 1012), (-200, 890),
]
OFFSET = (30, 80)


class EditorialPoster(Poster):
    """Retain the existing PDF/SVG primitives while versioning the outputs."""

    def __init__(self):
        self.pdf = canvas.Canvas(
            str(ROOT / f"{STEM}-80x180cm.pdf"),
            pagesize=(WIDTH * MM, HEIGHT * MM),
            pageCompression=1,
        )
        self.pdf.setTitle("Gesture Bridge")
        self.pdf.setAuthor("Gesture Bridge")
        self.pdf.setSubject("From gesture to understanding: a visual concept")
        self.pdf.scale(MM, MM)
        self.parts = [
            '<svg xmlns="http://www.w3.org/2000/svg" width="800mm" '
            'height="1800mm" viewBox="0 0 800 1800" '
            'role="img" aria-labelledby="title description">',
            '<title id="title">Gesture Bridge</title>',
            '<desc id="description">An original editorial poster: an '
            'anatomical hand landmark study transforms into a typographic '
            'letter and expands into language. Warm gray, teal and orange. '
            'The hand is conceptual artwork, not a live detection result.'
            '</desc>',
        ]
        self.text_bounds = []
        self.intentional_overlaps = [
            "The cropped wrist exits the left edge.",
            "The orange reply field intersects the teal quotation field.",
            "The opening quotation marks cross the orange field boundary.",
        ]

    def save(self):
        self.pdf.showPage()
        self.pdf.save()
        self.parts.append("</svg>")
        svg = "\n".join(self.parts)
        (ROOT / f"{STEM}.svg").write_text(svg, encoding="utf-8")
        (ROOT / f"{STEM}.html").write_text(
            '<!doctype html>\n<html lang="en"><head>'
            '<meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1">'
            '<title>Gesture Bridge</title><style>'
            '*{box-sizing:border-box}body{margin:0;background:#deddd6}'
            'main{width:min(100%,800px);margin:0 auto}'
            'svg{display:block;width:100%;height:auto}'
            '@page{size:800mm 1800mm;margin:0}'
            '@media print{body{background:none}main{width:800mm;'
            'margin:0}svg{width:800mm;height:1800mm}}'
            '</style></head><body><main>' + svg
            + '</main></body></html>', encoding="utf-8"
        )
        outside = [
            b for b in self.text_bounds
            if b["x"] < 0 or b["right"] > WIDTH
            or b["top"] < 0 or b["bottom"] > HEIGHT
        ]
        report = {
            "project_name": "Gesture Bridge",
            "dimensions_mm": [800, 1800],
            "landmark_count": len(LANDMARKS),
            "finger_chains": [ids for ids, _ in FINGERS],
            "connections": [
                [a, b] for chain in CHAINS
                for a, b in zip(chain, chain[1:])
            ],
            "landmark_reference": (
                "https://developers.google.com/edge/mediapipe/solutions/"
                "vision/hand_landmarker"
            ),
            "artwork_status": "Conceptual; no recognition result is claimed",
            "text_outside_page": outside,
            "intentional_overlaps": self.intentional_overlaps,
        }
        (ROOT / f"{STEM}-check.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if outside:
            raise ValueError(f"Text outside page: {outside}")


def move(point):
    return point[0] + OFFSET[0], point[1] + OFFSET[1]


def finger_segments():
    result = []
    for ids, radii in FINGERS:
        for i in range(len(ids) - 1):
            result.append((LANDMARKS[ids[i]], LANDMARKS[ids[i + 1]],
                           radii[i], radii[i + 1]))
    return result


def tapered_segment(poster, a, b, ra, rb, color):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    poster.polygon([
        move((a[0] + nx * ra, a[1] + ny * ra)),
        move((b[0] + nx * rb, b[1] + ny * rb)),
        move((b[0] - nx * rb, b[1] - ny * rb)),
        move((a[0] - nx * ra, a[1] - ny * ra)),
    ], fill=color)
    poster.circle(*move(a), ra, fill=color)
    poster.circle(*move(b), rb, fill=color)


def inside_polygon(x, y, points):
    inside = False
    j = len(points) - 1
    for i, (xi, yi) in enumerate(points):
        xj, yj = points[j]
        if ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def inside_segment(x, y, a, b, ra, rb):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    radius = ra + t * (rb - ra)
    return math.hypot(x - a[0] - t * dx,
                      y - a[1] - t * dy) < radius - 1.5


def draw_hand(poster):
    poster.polygon([move(point) for point in PALM], fill=HAND_GRAY)
    segments = finger_segments()
    for a, b, ra, rb in segments:
        tapered_segment(poster, a, b, ra, rb, HAND_GRAY)

    # A deterministic print screen follows the actual silhouette, not a box.
    for y in range(280, 1020, 5):
        for x in range(-205, 332, 5):
            if inside_polygon(x, y, PALM) or any(
                    inside_segment(x, y, *segment) for segment in segments):
                poster.circle(*move((x, y)), .35, fill=MID_GRAY)

    for chain in CHAINS:
        poster.path(
            [("M", *move(LANDMARKS[chain[0]]))]
            + [("L", *move(LANDMARKS[index])) for index in chain[1:]],
            stroke=INK, width=.65,
        )
    for index, point in enumerate(LANDMARKS):
        poster.circle(*move(point), 2.4, fill=PAPER, stroke=INK, width=.6)
        if index in [4, 8, 12, 16, 20]:
            x, y = move(point)
            poster.text(f"{index:02d}", x + 10, y - 11,
                        7.5, "Latin", MID_GRAY, tracking=.35)

    # Light anatomical creases keep the palm from reading as a glove icon.
    poster.path([
        ("M", 102, 716),
        ("C", 109, 674, 151, 647, 192, 654),
        ("M", 120, 744),
        ("C", 148, 738, 176, 744, 193, 759),
    ], stroke=MID_GRAY, width=.45)
    poster.text("00", *move((151, 702)), 7.5, "Latin", MID_GRAY)
    poster.line(344, 590, 371, 607, MID_GRAY, .5)
    poster.text("x / y", 375, 616, 8, "Latin", MID_GRAY)


def glyph_points():
    points = []
    for i in range(17):
        angle = math.radians(-45 - i * 270 / 16)
        points.append((523 + 88 * math.cos(angle),
                       833 + 88 * math.sin(angle)))
    points.extend([(605, 879), (605, 833), (567, 833), (540, 833)])
    return points


def connect_points(poster):
    targets = glyph_points()
    sources = [move(point) for point in LANDMARKS]
    source_order = sorted(range(21), key=lambda i: (
        sources[i][1], sources[i][0]))
    target_order = sorted(range(21), key=lambda i: (
        targets[i][1], targets[i][0]))
    mapping = dict(zip(source_order, target_order))

    # The typographic morph is a visual metaphor, not a classifier diagram.
    for index in [0, 4, 8, 12, 16, 20]:
        sx, sy = sources[index]
        tx, ty = targets[mapping[index]]
        poster.path([
            ("M", sx, sy),
            ("C", sx + 120, sy + 22, tx - 75, ty - 45, tx, ty),
        ], stroke=GRAY, width=.55)

    for index in range(21):
        sx, sy = sources[index]
        tx, ty = targets[mapping[index]]
        for t, radius, color in [(.63, 1.1, GRAY), (.83, 1.5, MID_GRAY)]:
            x = sx + (tx - sx) * t
            y = sy + (ty - sy) * t
            poster.circle(x, y, radius, fill=color)

    poster.path([("M", *targets[0])]
                + [("L", *point) for point in targets[1:]],
                stroke=TEAL, width=.8)
    for i, point in enumerate(targets):
        poster.circle(*point, 2.5, fill=TEAL)
        if i in [2, 10, 19]:
            poster.circle(*point, 4.1, fill=CORAL)

    # The same symbolic stem becomes a leading edge of the reply field.
    poster.path([
        ("M", 540, 833), ("L", 540, 952), ("L", 459, 952),
        ("L", 459, 1017),
    ], stroke=TEAL, width=.8)
    poster.text("21 landmarks / x, y", 592, 665,
                9.5, "Latin", MID_GRAY)
    poster.text("SPATIAL TO SYMBOLIC", 592, 685,
                8, "Latin", INK, tracking=1.15)


def draw_connection_field(poster):
    # A single stepped quotation field is cropped by the right page edge.
    poster.polygon([
        (459, 943), (800, 943), (800, 1528), (670, 1528),
        (670, 1661), (518, 1528), (163, 1528), (163, 1164),
        (341, 1164), (341, 1017), (459, 1017),
    ], fill=TEAL)

    poster.polygon([
        (370, 1408), (800, 1408), (800, 1800), (163, 1800),
        (163, 1528), (242, 1528), (242, 1453), (370, 1453),
    ], fill=ORANGE)

    # The two quotation marks are the final enlargement of the input dots.
    for x in [130, 236]:
        poster.circle(x, 1538, 38, fill=TEAL)
        poster.polygon([
            (x - 15, 1538), (x + 36, 1538),
            (x + 9, 1630), (x - 45, 1630),
        ], fill=TEAL)

    poster.text("FROM GESTURE", 44, 1038,
                27, "Latin", INK, tracking=-.3)
    poster.text("TO", 380, 1114, 25, "Latin", PAPER)
    poster.text("UNDER", 357, 1221,
                103, "Grotesk", PAPER, tracking=-4.5)
    poster.fitted("STANDING.", 205, 1337, 549,
                  font="Grotesk", colour=PAPER, tracking=-4)

    poster.text("Communication", 348, 1590,
                29, "Latin", INK, tracking=-.8)
    poster.text("beyond words.", 348, 1630,
                29, "Grotesk", INK, tracking=-.8)


def main():
    assert len(LANDMARKS) == 21
    assert {index for ids, _ in FINGERS for index in ids} == set(range(1, 21))
    assert len(glyph_points()) == 21
    p = EditorialPoster()
    p.rect(0, 0, WIDTH, HEIGHT, PAPER)
    p.text("Gesture", 40, 160, 115, "Latin", INK, tracking=-5)
    p.text("Bridge", 222, 286, 126, "Grotesk", INK, tracking=-5.5)

    p.text("ASSISTIVE COMMUNICATION", 44, 45,
           8.5, "Latin", MID_GRAY, tracking=1.25)
    p.line(622, 76, 756, 76, GRAY, .5)
    p.text("From isolation", 622, 102, 11.5, "Latin", INK)
    p.text("to connection.", 622, 120, 11.5, "Latin", INK)
    p.text("HAND / 21 LANDMARKS", 44, 324,
           8.5, "Latin", MID_GRAY, tracking=.65)

    draw_hand(p)
    connect_points(p)
    draw_connection_field(p)

    # Keep the footer on the same grid, with no feature-card layout.
    p.line(44, 1739, 756, 1739, INK, .65)
    p.text("Gesture Bridge", 44, 1766, 10.5, "Grotesk", INK)
    p.text("辅助沟通 / 概念设计", 343, 1766, 9, "CN", INK)
    p.text("部分功能开发验证中", 631, 1766, 8, "CN", INK)
    p.save()


if __name__ == "__main__":
    main()
