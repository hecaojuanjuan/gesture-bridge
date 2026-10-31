"""Create a dimensioned prototype enclosure and standard millimeter 3MF."""
import argparse
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools/cad"))
import manifold3d as md  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
ET.register_namespace("", NS)


def box(w, d, h, x=0, y=0, z=0):
    return md.Manifold.cube((w, d, h)).translate((x-w/2, y-d/2, z))


def cylinder(r, h, x=0, y=0, z=0):
    return md.Manifold.cylinder(h, r, circular_segments=48).translate((x, y, z))


def rounded(w, d, h, radius, z=0):
    parts = [cylinder(radius, h, x, y, z)
             for x in (-w/2+radius, w/2-radius)
             for y in (-d/2+radius, d/2-radius)]
    result = parts[0]
    for part in parts[1:]:
        result += part
    return result.hull()


def mesh(solid):
    assert solid.status() == md.Error.NoError, solid.status()
    raw = solid.to_mesh()
    result = trimesh.Trimesh(np.array(raw.vert_properties[:, :3]),
                             np.array(raw.tri_verts), process=True)
    assert result.is_watertight and result.is_winding_consistent
    assert result.volume > 0
    assert body_count(result) == 1, body_count(result)
    return result


def body_count(part):
    parent = list(range(len(part.vertices)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b, c in part.faces:
        parent[find(int(a))] = find(int(b))
        parent[find(int(c))] = find(int(b))
    return len({find(i) for i in range(len(parent))})


def make_parts(w, d, h):
    body = rounded(w, d, h, 6) - rounded(w-6, d-6, h+1, 3, 3)
    boss_x, boss_y = w/2-7, d/2-7
    for x in (-boss_x, boss_x):
        for y in (-boss_y, boss_y):
            body += cylinder(5.5, h, x, y)
    # Open-to-top access slots avoid long horizontal lintels.
    body -= box(w-34, 14, h, y=-d/2, z=38)
    body -= box(w-40, 14, h, y=d/2, z=18)
    for x in (-w/2, w/2):
        body -= box(14, d-38, h, x=x, z=18)
    # The speaker slides through its opening onto an internal support shelf.
    speaker_x = -23
    body += box(42, 16, 3, x=speaker_x, y=-d/2+10, z=7)
    body -= box(31, 14, 28, x=speaker_x, y=-d/2, z=10)
    for x in (speaker_x-20, speaker_x+20):
        body -= box(2.8, 14, 12, x=x, y=-d/2, z=17)
    mic = md.Manifold.cylinder(14, 3.8, circular_segments=48, center=True)
    body -= mic.rotate((90, 0, 0)).translate((36, -d/2, 25))
    # Tie slots next to the microphone retain its cable without pinching it.
    for x in (28, 44):
        body -= box(2.8, 14, 6, x=x, y=-d/2, z=22)
    # Floor slots permit adjustable trays, cable ties, and cable strain relief.
    for x in (-42, -24, 0, 24, 42):
        for y in (-20, 20):
            body -= box(3.2, 12, 5, x, y, -1)
    for x in (-boss_x, boss_x):
        for y in (-boss_y, boss_y):
            body -= cylinder(1.35, 16, x, y, h-15)

    lid = rounded(w, d, 4, 6)
    for x in (-boss_x, boss_x):
        for y in (-boss_y, boss_y):
            lid -= cylinder(1.7, 6, x, y, -1)
    # The gimbal is fixed to the floor; the deck clears its moving upper half.
    for x in (-22, 22):
        body -= box(3, 25, 5, x=x, z=-1)
    for y in (-21, 21):
        body -= box(48, 3, 5, y=y, z=-1)
    for x in (-13, 13):
        for y in (-11, 11):
            body -= box(9, 3.4, 5, x, y, -1)
    lid -= rounded(108, 92, 6, 8, -1)

    # Universal insulated board carriers; no unknown PCB hole pattern is assumed.
    tray = rounded(46, 43, 2.4, 2)
    for x in (-19, 19):
        for y in (-15, 15):
            tray += box(7, 7, 2, x, y, 2.2)
    for x in (-18, 18):
        tray -= box(2.8, 17, 8, x=x, z=-1)
    tray -= box(14, 3.2, 8, z=-1)
    return [mesh(body), mesh(lid), mesh(tray), mesh(tray)]


def element(parent, tag, **attrs):
    return ET.SubElement(parent, f"{{{NS}}}{tag}", {k: str(v) for k, v in attrs.items()})


def write_3mf(path, parts, names, transforms):
    model = ET.Element(f"{{{NS}}}model", unit="millimeter", attrib={
                       "{http://www.w3.org/XML/1998/namespace}lang": "en-US"})
    element(model, "metadata",
            name="Title").text = "Gesture Bridge enclosure prototype v1"
    element(model, "metadata",
            name="Description").text = "Hardware fit is provisional; verify dimensions before printing."
    resources = element(model, "resources")
    for index, (part, name) in enumerate(zip(parts, names), 1):
        obj = element(resources, "object", id=index, type="model", name=name)
        node = element(obj, "mesh")
        vertices = element(node, "vertices")
        for vertex in part.vertices:
            element(vertices, "vertex", **
                    dict(zip("xyz", (f"{v:.6f}" for v in vertex))))
        triangles = element(node, "triangles")
        for a, b, c in part.faces:
            element(triangles, "triangle", v1=a, v2=b, v3=c)
    build = element(model, "build")
    for index, transform in enumerate(transforms, 1):
        element(build, "item", objectid=index,
                transform=" ".join(f"{v:.6f}" for v in transform))
    content = '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'
    rels = '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("3D/3dmodel.model", ET.tostring(model,
                         encoding="utf-8", xml_declaration=True))
    # Independently re-read the actual packaged coordinates and triangle indices.
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        root = ET.fromstring(archive.read("3D/3dmodel.model"))
    assert root.attrib["unit"] == "millimeter"
    for obj in root.findall(f"{{{NS}}}resources/{{{NS}}}object"):
        vv = [[float(v.attrib[k]) for k in "xyz"]
              for v in obj.findall(f".//{{{NS}}}vertex")]
        ff = [[int(f.attrib[k]) for k in ("v1", "v2", "v3")]
              for f in obj.findall(f".//{{{NS}}}triangle")]
        check = trimesh.Trimesh(vv, ff, process=False)
        assert check.is_watertight and check.volume > 0


def render(parts, path, w, d, h):
    img = Image.new("RGB", (1800, 1300), "#f3f6fa")
    draw = ImageDraw.Draw(img)

    def label(x, y, value, size=29, color="#30435b"):
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
        draw.text((x, y), value, font=font, fill=color)
    label(65, 40, "颔语 · 低矮底盒 / 上层云台外露", 48)
    label(67, 112, f"原型 v1  |  下盒 {w:g} × {d:g} × {h:g} mm  |  顶盖厚 4 mm", 27)
    # Hardware silhouettes are shown only in this explanatory preview.
    phantom = mesh(box(36, 33, 7))
    support = mesh(box(40, 35, 35))
    camera = mesh(box(35, 8, 38))
    entries = [(parts[0], (0, 0, 0), (170, 188, 210)),
               (parts[1], (0, 0, h+9), (91, 133, 180)),
               (phantom, (0, 0, 3), (77, 94, 113)),
               (support, (0, 10, 10), (92, 108, 128)),
               (camera, (0, -22, 45), (55, 76, 101))]
    lens = mesh(md.Manifold.cylinder(
        7, 7, circular_segments=40).rotate((90, 0, 0)))
    entries.append((lens, (0, -26, 69), (38, 49, 65)))
    board_preview = mesh(box(40, 60, 3))
    for x in (-50, 50):
        entries.append((board_preview, (x, 8, 5), (65, 139, 121)))
    right = np.array([.83, .56, 0])
    up = np.array([-.30, .45, .84])
    depth = np.cross(right, up)

    def view(entries, center, scale):
        triangles = []
        light = np.array([-.5, -.6, .8])
        light /= np.linalg.norm(light)
        for part, shift, color in entries:
            vertices = part.vertices + np.array(shift)
            for face, normal in zip(part.faces, part.face_normals):
                if np.dot(normal, depth) <= 0:
                    continue
                points = vertices[face]
                projected = [(center[0]+np.dot(p, right)*scale,
                              center[1]-np.dot(p, up)*scale) for p in points]
                shade = .58 + .42 * max(0, np.dot(normal, light))
                triangles.append((np.dot(points.mean(axis=0), depth), projected,
                                  tuple(int(c*shade) for c in color)))
        for _, polygon, color in sorted(triangles, key=lambda row: row[0]):
            draw.polygon(polygon, fill=color)
    view(entries, (570, 900), 4.2)
    label(75, 1160, "摄像头 / 云台示意不包含在打印零件中", 26)
    view([(parts[1], (0, 0, 0), (91, 133, 180))], (1370, 380), 2.65)
    label(1110, 520, "顶盖：108×92 mm 云台让位口", 27)
    view([(parts[2], (0, 0, 0), (170, 188, 210))], (1370, 710), 3)
    label(1110, 800, "小型模块托片 ×2（非定制孔位）", 27)
    label(1110, 910, "正面：31×28 mm 喇叭开口", 27)
    label(1110, 960, "正面右侧：Ø7.6 mm 麦克风口", 27)
    label(1110, 1010, "侧面 / 背面：开放接线检修口", 27)
    label(1110, 1060, "四角：顶盖固定孔", 27)
    label(1110, 1110, "绿色板位为示意，尺寸待确认", 26)
    label(65, 1230, "尺寸待确认：主板总宽/深、喇叭厚度、安装孔距；本图不是实物装配验收。", 26)
    img.save(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=float, default=160)
    parser.add_argument("--depth", type=float, default=120)
    parser.add_argument("--height", type=float, default=41)
    args = parser.parse_args()
    w, d, h = args.width, args.depth, args.height
    if w < 128 or d < 112 or h < 40:
        parser.error(
            "Prototype openings require width>=128, depth>=112, height>=40")
    out = ROOT / "artifacts/enclosure-v1"
    out.mkdir(parents=True, exist_ok=True)
    parts = make_parts(w, d, h)
    names = ["enclosure_body", "gimbal_top_deck",
             "board_carrier_A", "board_carrier_B"]
    identity = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    transforms = [identity+[w/2, d/2, 0],
                  [0, 1, 0, -1, 0, 0, 0, 0, 1, w+6+d/2, w/2, 0],
                  identity+[25, max(w, d)+30, 0],
                  identity+[77, max(w, d)+30, 0]]
    write_3mf(out / "gesture-bridge-enclosure-v1.3mf",
              parts, names, transforms)
    for part, name in zip(parts[:2], names):
        write_3mf(out / f"{name}.3mf", [part],
                  [name], [identity+[w/2, d/2, 0]])
    render(parts, out / "enclosure-preview.png", w, d, h)
    report = {"unit": "millimeter", "body_external": [w, d, h],
              "body_internal_nominal": [w-6, d-6, h-3],
              "assembled_case_height": h+4,
              "speaker_opening": [31, 28], "microphone_opening_diameter": 7.6,
              "gimbal_base_from_user": [36, 33], "gimbal_total_height_from_user": 80,
              "deck_opening": [108, 92], "gimbal_mounting_plane_z": 3,
              "parts": [{"name": name, "watertight": bool(p.is_watertight),
                         "connected_bodies": body_count(p),
                         "volume_mm3": float(p.volume),
                         "bounds_mm": p.extents.tolist(),
                         "triangles": len(p.faces)} for name, p in zip(names, parts)],
              "fit_verified": False, "hardware_tested": False,
              "assumptions": ["Boards lie on floor; board footprints and connector heights unknown",
                              "45 mm interpreted as assembled lower enclosure height; body 41 mm plus deck 4 mm",
                              "Speaker thickness and mounting hole locations unknown",
                              "Gimbal sweep not measured; no printed wall above deck",
                              "Four M3x10 thread-forming screws are proposed; actual fit needs testing"]}
    (out / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(out / "gesture-bridge-enclosure-v1.3mf")


if __name__ == "__main__":
    main()
