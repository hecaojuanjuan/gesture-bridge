"""Build a rounded enclosure while preserving the v1 hardware interfaces."""

import json
import math
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import generate_enclosure as base

md = base.md
np = base.np
trimesh = base.trimesh
OUT = base.ROOT / "artifacts/enclosure-milk-egg-v2"


def solid(part):
    return md.Manifold(md.Mesh64(
        np.asarray(part.vertices, dtype=np.float64),
        np.asarray(part.faces, dtype=np.uint64)))


def mesh(s):
    raw = s.to_mesh64()
    part = trimesh.Trimesh(np.array(raw.vert_properties[:, :3]),
                           np.array(raw.tri_verts), process=True)
    assert part.is_watertight and part.is_winding_consistent
    assert part.volume > 0 and base.body_count(part) == 1
    return part


def rounded_loft(levels):
    """Loft corresponding rounded-rectangle rings with flat end caps."""
    vertices = []
    for z, delta in levels:
        radius = 6 + 2 * delta
        for cx, cy, start in ((80 + delta - radius,
                               60 + delta - radius, 0),
                              (-80 - delta + radius,
                               60 + delta - radius, 90),
                              (-80 - delta + radius,
                               -60 - delta + radius, 180),
                              (80 + delta - radius,
                               -60 - delta + radius, 270)):
            for angle in np.linspace(start, start + 90, 13):
                a = math.radians(angle)
                vertices.append((cx + radius * math.cos(a),
                                 cy + radius * math.sin(a), z))
    count = 52
    faces = []
    for row in range(len(levels) - 1):
        for i in range(count):
            a = row * count + i
            b = row * count + (i + 1) % count
            faces.extend(((a, b, b + count), (a, b + count, a + count)))
    for i in range(1, count - 1):
        faces.append((0, i + 1, i))
        end = (len(levels) - 1) * count
        faces.append((end, end + i, end + i + 1))
    return md.Manifold(md.Mesh64(np.asarray(vertices, dtype=np.float64),
                                 np.asarray(faces, dtype=np.uint64)))


def access_cutters():
    cutters = base.box(126, 24, 44, y=-60, z=38)
    cutters += base.box(120, 24, 44, y=60, z=18)
    for x in (-80, 80):
        cutters += base.box(24, 82, 44, x=x, z=18)
    cutters += base.box(31, 24, 28, x=-23, y=-60, z=10)
    for x in (-43, -3):
        cutters += base.box(2.8, 24, 12, x=x, y=-60, z=17)
    mic = md.Manifold.cylinder(24, 3.8, circular_segments=48, center=True)
    cutters += mic.rotate((90, 0, 0)).translate((36, -60, 25))
    for x in (28, 44):
        cutters += base.box(2.8, 24, 6, x=x, y=-60, z=22)
    return cutters


def recolor(path, colors, parts):
    with zipfile.ZipFile(path) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    root = ET.fromstring(files['3D/3dmodel.model'])
    ns = {'m': base.NS}
    root.find('m:metadata', ns).text = 'Gesture Bridge Milk Egg v2'
    resources = root.find('m:resources', ns)
    palette = base.element(resources, 'basematerials', id=99)
    for index, color in enumerate(colors):
        base.element(palette, 'base', name=f'Finish {index + 1}',
                     displaycolor=color)
    for index, obj in enumerate(resources.findall('m:object', ns)):
        obj.set('pid', '99')
        obj.set('pindex', str(index))
        vertices = obj.findall('m:mesh/m:vertices/m:vertex', ns)
        for vertex, coordinates in zip(vertices, parts[index].vertices):
            for axis, value in zip('xyz', coordinates):
                vertex.set(axis, f'{value:.15g}')
    files['3D/3dmodel.model'] = ET.tostring(
        root, encoding='utf-8', xml_declaration=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)


def preview(parts):
    """Render the actual printable surfaces with a software depth buffer."""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1600, 1100
    canvas = np.full((height, width, 3), (245, 242, 235), dtype=np.uint8)
    depth_buffer = np.full((height, width), -np.inf)
    right = np.array([.83, .56, 0])
    up = np.array([-.30, .45, .84])
    direction = np.cross(right, up)
    light = np.array([-.4, -.6, .8])
    light /= np.linalg.norm(light)

    def draw_part(part, shift, color, center, scale):
        vv = part.vertices + np.array(shift)
        points = np.column_stack((center[0] + vv @ right * scale,
                                  center[1] - vv @ up * scale))
        depths = vv @ direction
        for face, normal in zip(part.faces, part.face_normals):
            if normal @ direction <= 0:
                continue
            triangle = points[face]
            low = np.maximum(np.floor(triangle.min(axis=0)).astype(int), 0)
            high = np.minimum(np.ceil(triangle.max(axis=0)).astype(int),
                              [width - 1, height - 1])
            if np.any(high < low):
                continue
            xx, yy = np.meshgrid(np.arange(low[0], high[0] + 1),
                                 np.arange(low[1], high[1] + 1))
            a, b, c = triangle
            denominator = ((b[1] - c[1]) * (a[0] - c[0])
                           + (c[0] - b[0]) * (a[1] - c[1]))
            if abs(denominator) < 1e-9:
                continue
            u = ((b[1] - c[1]) * (xx - c[0])
                 + (c[0] - b[0]) * (yy - c[1])) / denominator
            v = ((c[1] - a[1]) * (xx - c[0])
                 + (a[0] - c[0]) * (yy - c[1])) / denominator
            w = 1 - u - v
            zz = u * depths[face[0]] + v * depths[face[1]]
            zz += w * depths[face[2]]
            region = depth_buffer[low[1]:high[1] + 1, low[0]:high[0] + 1]
            mask = (u >= -1e-6) & (v >= -1e-6) & (w >= -1e-6)
            mask &= zz > region
            region[mask] = zz[mask]
            shade = .58 + .42 * max(0, normal @ light)
            pixels = canvas[low[1]:high[1] + 1, low[0]:high[0] + 1]
            pixels[mask] = np.array(color) * shade

    draw_part(parts[0], (0, 0, 0), (246, 238, 216), (570, 690), 4.3)
    draw_part(parts[1], (0, 0, 41), (246, 208, 122), (570, 690), 4.3)
    draw_part(parts[1], (0, 0, 0), (246, 208, 122), (1300, 350), 2.1)
    img = Image.fromarray(canvas)
    draw = ImageDraw.Draw(img)

    def label(x, y, text, size=26):
        font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', size)
        draw.text((x, y), text, font=font, fill='#4c493e')

    label(65, 40, '奶蛋 · 圆润外壳 v2', 46)
    label(65, 110, '实际打印网格预览 | 奶白底盒 + 奶黄可拆顶盖', 27)
    label(1060, 490, '顶盖单件 / 厚 4 mm')
    label(1060, 550, '云台口 108 × 92 mm')
    label(1060, 600, '喇叭口 31 × 28 mm')
    label(1060, 650, '麦克风孔 Ø7.6 mm')
    label(65, 930, '外廓约 168 × 128 × 45 mm；原固定孔、内腔与底部安装槽保留。')
    label(65, 980, '摄像头与上层云台外露；图中不添加虚构硬件。实物装配及全行程仍需验证。', 23)
    img.save(OUT / 'milk-egg-preview.png')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    old = base.make_parts(160, 120, 41)
    original_body, original_lid = map(solid, old[:2])
    levels = [(float(z), 4 * math.sin(math.pi * z / 41) ** .65)
              for z in np.linspace(0, 41, 83)]
    levels[0], levels[-1] = (0, 0), (41, 0)
    outer = rounded_loft(levels)
    skin = outer - base.rounded(160, 120, 43, 6, -1)
    body = original_body + skin
    body -= access_cutters()
    # Extend the original lid outward only, maintaining all original holes.
    lid_outer = rounded_loft([(0, 0), (.4, .7), (1, 1.3),
                              (2, 1.6), (3, 1.3), (3.6, .7), (4, 0)])
    lid_skin = lid_outer - base.rounded(160, 120, 6, 6, -1)
    lid = original_lid + lid_skin
    parts = [mesh(body), mesh(lid), *old[2:]]
    # Exact booleans verify that the redesign removes no original material
    # and adds no material inside the original external envelope.
    body_lost = (original_body - body).volume()
    lid_lost = (original_lid - lid).volume()
    intrusion = ((body - original_body)
                 ^ base.rounded(160, 120, 41, 6)).volume()
    overlap = (body ^ lid.translate((0, 0, 41))).volume()
    assert abs(body_lost) < 1e-3, body_lost
    assert abs(lid_lost) < 1e-3, lid_lost
    assert abs(intrusion) < 1e-3, intrusion
    assert abs(overlap) < 1e-3, overlap
    names = ['milk_egg_body', 'milk_egg_lid',
             'optional_carrier_A', 'optional_carrier_B']
    colors = ['#F6EED8FF', '#F6D07AFF', '#F6EED8FF', '#F6EED8FF']
    identity = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    transforms = [identity + [84, 64, 0], identity + [254, 64, 0],
                  identity + [27, 159, 0], identity + [81, 159, 0]]
    path = OUT / 'gesture-bridge-milk-egg-v2.3mf'
    base.write_3mf(path, parts, names, transforms)
    recolor(path, colors, parts)
    for part, name, color in zip(parts[:2], names, colors):
        target = OUT / f'{name}.3mf'
        base.write_3mf(target, [part], [name],
                       [identity + [84, 64, 0]])
        recolor(target, [color], [part])
    for target in OUT.glob('*.3mf'):
        scene = trimesh.load(target, force='scene')
        expected = 4 if target == path else 1
        assert len(scene.geometry) == expected
        for imported in scene.geometry.values():
            assert imported.is_watertight
            assert imported.is_winding_consistent and imported.volume > 0
    report = {
        'unit': 'millimeter', 'assembled_height_mm': 45,
        'parts': [{'name': name, 'size_mm': part.extents.tolist(),
                   'watertight': bool(part.is_watertight),
                   'winding_consistent': bool(part.is_winding_consistent),
                   'connected_bodies': base.body_count(part),
                   'volume_mm3': float(part.volume)}
                  for name, part in zip(names, parts)],
        'compatibility_boolean_checks_mm3': {
            'original_body_material_removed': body_lost,
            'original_lid_material_removed': lid_lost,
            'new_material_inside_original_body_envelope': intrusion,
            'assembled_body_lid_overlap': overlap},
        'independent_trimesh_import_passed': True,
        'fit_verified': False, 'hardware_tested': False,
        'notes': ['Original interior, mounting slots and holes preserved.',
                  'Outer bulge adds approximately 4 mm per side.',
                  'Side, rear and speaker access cuts extend through skin.',
                  'Color metadata does not select printer filaments.',
                  'Gimbal sweep and real hardware fit remain unmeasured.']}
    (OUT / 'validation.json').write_text(
        json.dumps(report, indent=2), encoding='utf-8')
    preview(parts)
    print(json.dumps(report, indent=2))
    print(path)


if __name__ == '__main__':
    main()
