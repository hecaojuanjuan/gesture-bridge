"""Create a removable two-piece character cover around the existing v1 case."""

import json
import math
import zipfile
from xml.etree import ElementTree as ET

import generate_enclosure as base
import generate_milk_egg_enclosure as helpers

md, np, trimesh = base.md, base.np, base.trimesh
OUT = base.ROOT / 'artifacts/milk-egg-protective-cover-v7-100mm'
FLOOR = 2.4
SPLIT = 42.0
HEIGHT = 100.0
WALL = 2.8
EYE_Z = 65 + (162 - 65) * (HEIGHT - 65) / (230 - 65)
MOUTH_Z = EYE_Z - max(12, 25 * (HEIGHT - 65) / (230 - 65))
FACE_SCALE = min(1, (HEIGHT - 65) / 70)
PROFILE = np.array([
    [0, 98, 80, 4], [3, 100, 81, 4], [15, 105, 85, 4],
    [42, 110, 88, 3.8], [65, 112, 90, 3.3],
    [90, 110, 88, 2.9], [120, 105, 84, 2.6],
    [150, 94, 76, 2.35], [175, 79, 64, 2.15],
    [195, 60, 49, 2.05], [210, 41, 34, 2],
    [220, 25, 21, 2], [227, 11, 9, 2], [230, 2, 2, 2]])
SLOPES = np.diff(PROFILE[:, 1:], axis=0) / np.diff(
    PROFILE[:, 0])[:, None]
TANGENTS = np.zeros_like(PROFILE[:, 1:])
TANGENTS[0], TANGENTS[-1] = SLOPES[0], SLOPES[-1]
for row in range(1, len(PROFILE) - 1):
    for axis in range(3):
        left, right = SLOPES[row - 1, axis], SLOPES[row, axis]
        if left * right > 0:
            h0 = PROFILE[row, 0] - PROFILE[row - 1, 0]
            h1 = PROFILE[row + 1, 0] - PROFILE[row, 0]
            w0, w1 = 2 * h1 + h0, h1 + 2 * h0
            TANGENTS[row, axis] = (w0 + w1) / (w0 / left + w1 / right)


def profile(z):
    row = min(max(np.searchsorted(PROFILE[:, 0], z) - 1, 0),
              len(PROFILE) - 2)
    h = PROFILE[row + 1, 0] - PROFILE[row, 0]
    t = (z - PROFILE[row, 0]) / h
    original = ((2 * t ** 3 - 3 * t ** 2 + 1) * PROFILE[row, 1:]
                + (t ** 3 - 2 * t ** 2 + t) * h * TANGENTS[row]
                + (-2 * t ** 3 + 3 * t ** 2) * PROFILE[row + 1, 1:]
                + (t ** 3 - t ** 2) * h * TANGENTS[row + 1])
    if z <= 65:
        return original
    if HEIGHT <= 110:
        # A single broad cubic superellipse keeps camera clearance without
        # introducing a shoulder or separate dome in the compact cover.
        t = (z - 65) / (HEIGHT - 65)
        radius = max(0, 1 - t ** 3) ** (1 / 3)
        blend = min((z - 65) / (HEIGHT - 70), 1)
        blend = blend * blend * (3 - 2 * blend)
        return np.array([112 * radius, 90 * radius, 3.3 - 1.3 * blend])
    # One continuous egg curve narrows smoothly from belly to crown.
    # Its square-root pole gives a rounded top with a horizontal tangent;
    # the taper factor narrows the shoulders without forming a neck.
    t = (z - 65) / (HEIGHT - 65)
    radius = math.sqrt(max(0, 1 - t * t)) * (1 - .10 * t * t)
    blend = min((z - 65) / 75, 1)
    blend = blend * blend * (3 - 2 * blend)
    return np.array([112 * radius, 90 * radius, 3.3 - 1.3 * blend])


def loft(start, end, inset=0, step=1.5, breaks=(), profile_shift=0):
    """Build a closed superellipse loft with coherent ring topology."""
    levels = sorted(set([start, end, *breaks, *np.arange(start, end, step),
                         *[z for z in PROFILE[:, 0] if start < z < end]]))
    if end == HEIGHT:
        levels = sorted(set(levels + list(np.arange(HEIGHT - 5, HEIGHT, .25))))
    count = 160
    vv, ff = [], []
    pole = None
    for z in levels:
        a, b, power = profile(z + profile_shift)
        offset = inset(z) if callable(inset) else inset
        a, b = a - offset, b - offset
        if abs(a) < 1e-9 and abs(b) < 1e-9 and z == end:
            pole = (0, 0, z)
            continue
        assert a > 0 and b > 0
        for angle in np.arange(count) * (2 * math.pi / count):
            c, s = math.cos(angle), math.sin(angle)
            vv.append((a * math.copysign(abs(c) ** (2 / power), c),
                       b * math.copysign(abs(s) ** (2 / power), s), z))
    rings = len(vv) // count
    for row in range(rings - 1):
        for i in range(count):
            a = row * count + i
            b = row * count + (i + 1) % count
            ff.extend(((a, b, b + count), (a, b + count, a + count)))
    for i in range(1, count - 1):
        ff.append((0, i + 1, i))
        if pole is None:
            end_index = (rings - 1) * count
            ff.append((end_index, end_index + i, end_index + i + 1))
    if pole is not None:
        pole_index = len(vv)
        vv.append(pole)
        end_index = (rings - 1) * count
        for i in range(count):
            ff.append((end_index + i, end_index + (i + 1) % count,
                       pole_index))
    result = md.Manifold(md.Mesh64(np.asarray(vv, dtype=np.float64),
                                   np.asarray(ff, dtype=np.uint64)))
    assert result.status() == md.Error.NoError
    return result


def load_existing():
    path = base.ROOT / 'artifacts/enclosure-v1/gesture-bridge-enclosure-v1.3mf'
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('3D/3dmodel.model'))
    ns = {'m': base.NS}
    parts = []
    for obj in root.findall('m:resources/m:object', ns)[:2]:
        vv = [[float(v.get(k)) for k in 'xyz']
              for v in obj.findall('m:mesh/m:vertices/m:vertex', ns)]
        ff = [[int(t.get(k)) for k in ('v1', 'v2', 'v3')]
              for t in obj.findall('m:mesh/m:triangles/m:triangle', ns)]
        parts.append(trimesh.Trimesh(vv, ff, process=True))
    parts[0].apply_translation((0, 0, FLOOR))
    parts[1].apply_translation((0, 0, FLOOR + 41))
    return parts


def cylinder_y(radius, x, z, length=160):
    return md.Manifold.cylinder(length, radius, circular_segments=64,
                                center=True).rotate((90, 0, 0)).translate(
                                    (x, -60, z))


def face_color(points):
    x, y, z = points.mean(axis=0)
    if y < -15:
        for eye in (-33, 33):
            distance = (((x - eye) / (10 * FACE_SCALE)) ** 2
                        + ((z - EYE_Z) / (13 * FACE_SCALE)) ** 2)
            if distance < .20:
                return 3
            if distance < 1:
                return 2
        if abs(x) < 17 and abs(z - (MOUTH_Z + .014 * x * x)) < 1.5:
            return 4
    return 0


def write_3mf(path, parts, names, transforms, upper_index=None):
    """Write millimeter meshes with optional surface appearance colors."""
    root = ET.Element(f'{{{base.NS}}}model', unit='millimeter')
    base.element(root, 'metadata', name='Title').text = (
        'Milk Egg compact 100 mm protective cover v7')
    resources = base.element(root, 'resources')
    palette = base.element(resources, 'basematerials', id=99)
    for name, color in [('Custard yellow', '#F5CB64FF'),
                        ('Warm yellow', '#F1C15AFF'),
                        ('Iris green', '#88A45EFF'),
                        ('Pupil', '#282D24FF'), ('Smile', '#A07832FF')]:
        base.element(palette, 'base', name=name, displaycolor=color)
    for index, (part, name) in enumerate(zip(parts, names), 1):
        obj = base.element(resources, 'object', id=index, type='model',
                           name=name, pid=99, pindex=0)
        node = base.element(obj, 'mesh')
        vertices = base.element(node, 'vertices')
        for vertex in part.vertices:
            base.element(vertices, 'vertex', **dict(zip(
                'xyz', [f'{v:.15g}' for v in vertex])))
        triangles = base.element(node, 'triangles')
        for face in part.faces:
            attributes = dict(zip(('v1', 'v2', 'v3'), map(int, face)))
            if index - 1 == upper_index:
                color = face_color(part.vertices[face])
                attributes.update(pid=99, p1=color, p2=color, p3=color)
            base.element(triangles, 'triangle', **attributes)
    build = base.element(root, 'build')
    for index, transform in enumerate(transforms, 1):
        base.element(build, 'item', objectid=index,
                     transform=' '.join(str(v) for v in transform))
    content_types = ('<?xml version="1.0"?><Types xmlns="http://schemas.'
                     'openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/'
                     'vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="model" ContentType="application/'
                     'vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    relationships = ('<?xml version="1.0"?><Relationships xmlns="http://'
                     'schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
                     'Type="http://schemas.microsoft.com/3dmanufacturing/'
                     '2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', content_types)
        archive.writestr('_rels/.rels', relationships)
        archive.writestr('3D/3dmodel.model', ET.tostring(
            root, encoding='utf-8', xml_declaration=True))
    imported = trimesh.load(path, force='scene')
    assert len(imported.geometry) == len(parts)
    for part in imported.geometry.values():
        assert part.is_watertight and part.is_winding_consistent
        assert part.volume > 0 and base.body_count(part) == 1


def render(lower, upper, old):
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1800, 1250
    canvas = np.full((height, width, 3), (247, 244, 234), dtype=np.uint8)
    buffer = np.full((height, width), -np.inf)
    right = np.array([.94, .342, 0])
    up = np.array([-.103, .282, .954])
    direction = np.cross(right, up)
    light = np.array([-.4, -.6, .8])
    light /= np.linalg.norm(light)
    colors = [(245, 203, 100), (241, 193, 90), (136, 164, 94),
              (40, 45, 36), (160, 120, 50)]

    def draw_part(part, center, scale, color, colored=False):
        vertices = part.vertices
        projected = np.column_stack((center[0] + vertices @ right * scale,
                                     center[1] - vertices @ up * scale))
        depths = vertices @ direction
        for face, normal in zip(part.faces, part.face_normals):
            if normal @ direction <= 0:
                continue
            tri = projected[face]
            lo = np.maximum(np.floor(tri.min(axis=0)).astype(int), 0)
            hi = np.minimum(np.ceil(tri.max(axis=0)).astype(int),
                            [width - 1, height - 1])
            if np.any(hi < lo):
                continue
            xx, yy = np.meshgrid(np.arange(lo[0], hi[0] + 1),
                                 np.arange(lo[1], hi[1] + 1))
            a, b, c = tri
            denominator = ((b[1] - c[1]) * (a[0] - c[0])
                           + (c[0] - b[0]) * (a[1] - c[1]))
            if abs(denominator) < 1e-9:
                continue
            u = ((b[1] - c[1]) * (xx - c[0])
                 + (c[0] - b[0]) * (yy - c[1])) / denominator
            v = ((c[1] - a[1]) * (xx - c[0])
                 + (a[0] - c[0]) * (yy - c[1])) / denominator
            w = 1 - u - v
            depth = u * depths[face[0]] + v * depths[face[1]]
            depth += w * depths[face[2]]
            region = buffer[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1]
            mask = (u >= -1e-6) & (v >= -1e-6) & (w >= -1e-6)
            mask &= depth > region
            region[mask] = depth[mask]
            tint = colors[face_color(vertices[face])] if colored else color
            shade = .65 + .35 * max(0, normal @ light)
            pixels = canvas[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1]
            pixels[mask] = np.array(tint) * shade

    draw_part(lower, (440, 990), 3.1, colors[0])
    draw_part(upper, (440, 990), 3.1, colors[0], True)
    draw_part(lower, (1320, 970), 3.3, colors[0])
    for part in old:
        draw_part(part, (1320, 970), 3.3, (170, 178, 181))
    # The gray camera/gimbal proxy is illustrative and is not exported.
    proxies = [base.box(36, 33, 35, z=FLOOR + 3),
               base.box(36, 16, 37, y=-12, z=FLOOR + 46)]
    for proxy in proxies:
        draw_part(helpers.mesh(proxy), (1320, 970), 3.3, (85, 91, 96))
    img = Image.fromarray(canvas)
    draw = ImageDraw.Draw(img)

    def label(x, y, text, size=27):
        font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', size)
        draw.text((x, y), text, font=font, fill='#51472e')

    label(65, 40, '奶蛋 · 100 mm 矮版保护壳 v7', 46)
    label(65, 112, '外加套壳｜保留原底盒｜上盖取下后运行', 29)
    label(250, 1090, '合盖保护 · 完整奶蛋', 30)
    label(1110, 1090, '取下上盖 · 露出原设备', 30)
    label(1020, 310, '下壳最高 42 mm，低于原 45 mm', 28)
    label(1020, 365, '拾音 / 发声 / 灯窗 / 接线开口', 28)
    label(1020, 420, '浅插接定位，上盖可整体提起', 28)
    label(1020, 475, '灰色为原底盒；相机支架仅作示意', 25)
    label(
        65, 1170, f'外廓约 224 × 180 × {HEIGHT:g} mm；上盖打印高 {HEIGHT - 36.5:g} mm，须设置内部支撑。', 27)
    img.save(OUT / 'milk-egg-cover-preview.png')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    old = load_existing()
    lower = loft(0, SPLIT) - loft(FLOOR, SPLIT + .1, WALL)
    # Locate the existing case with a 1 mm side clearance at four stops.
    for x in (-82, 82):
        lower += base.box(2, 18, 6, x=x, z=2)
    for y in (-62, 62):
        lower += base.box(18, 2, 6, y=y, z=2)
    # Adjustable bottom tie slots follow the old floor slot locations.
    for x in (-42, 42):
        for y in (-20, 20):
            lower -= base.box(3.2, 12, 5, x=x, y=y, z=-1)
    # Ports cut through the entire new skin at the original component axes.
    lower -= base.box(39, 90, 38, x=-23, y=-90, z=8 + FLOOR)
    lower -= cylinder_y(6, 36, 25 + FLOOR)
    lower -= base.box(126, 90, 12, y=-90, z=34)
    for x in (-105, 105):
        lower -= base.box(60, 86, 25, x=x, z=18 + FLOOR)
    lower -= base.box(124, 70, 25, y=90, z=18 + FLOOR)
    # Model the tongue and cap in one continuous loft to avoid coincident
    # surfaces at the slip-fit shoulder. The tongue extends below the seam.
    upper = loft(36.5, HEIGHT,
                 lambda z: WALL + .35 if z <= 42.24 else 0,
                 breaks=(42.24, 42.25))
    upper -= loft(36.4, HEIGHT - 5,
                  lambda z: WALL + 2.1 if z <= 44.49 else WALL,
                  breaks=(44.49, 44.5), profile_shift=2.4)
    # Engrave eyes and a smile shallowly, without piercing the cap.
    core_start = 36.5 + math.floor((MOUTH_Z - 13 - 36.5) / 1.5) * 1.5
    protected_core = loft(core_start,
                          min(HEIGHT - 1, EYE_Z + 20 * FACE_SCALE), .65)
    eyes = (cylinder_y(10 * FACE_SCALE, -33, EYE_Z)
            + cylinder_y(10 * FACE_SCALE, 33, EYE_Z))
    for x in (-33, 33):
        eyes -= cylinder_y(8.4 * FACE_SCALE, x, EYE_Z)
    smile = None
    for x in np.linspace(-17, 17, 40):
        stroke = cylinder_y(1, float(x), MOUTH_Z + .014 * x * x)
        smile = stroke if smile is None else smile + stroke
    if HEIGHT > 110:
        upper -= (eyes + smile) - protected_core
    parts = [helpers.mesh(lower), helpers.mesh(upper)]
    old_solid = helpers.solid(old[0]) + helpers.solid(old[1])
    collision_lower = (lower ^ old_solid).volume()
    collision_upper = (upper ^ old_solid).volume()
    collision_seam = (lower ^ upper).volume()
    envelope = base.rounded(162, 122, 45.2, 5, FLOOR)
    clearance_overlap = ((lower + upper) ^ envelope).volume()
    # A measured gimbal model is unavailable. Check a declared conservative
    # storage proxy, not an invented full-motion hardware envelope.
    proxy = base.box(108, 92, 44, z=FLOOR + 45)
    proxy_collision = ((lower + upper) ^ proxy).volume()
    for value in (collision_lower, collision_upper, collision_seam,
                  clearance_overlap, proxy_collision):
        assert abs(value) < .001, value
    identity = [1, 0, 0, 0, 1, 0, 0, 0, 1]
    names = ['lower_protective_shell', 'upper_removable_cover']
    write_3mf(OUT / 'milk-egg-protective-cover-v7-100mm.3mf', parts, names,
              [identity + [112, 90, 0], identity + [348, 90, -36.5]], 1)
    write_3mf(OUT / 'lower-shell.3mf', [parts[0]], [names[0]],
              [identity + [112, 90, 0]])
    write_3mf(OUT / 'upper-cover.3mf', [parts[1]], [names[1]],
              [identity + [112, 90, -36.5]], 0)
    sample_region = base.box(50, 42, 11, x=88, y=65, z=34)
    samples = [helpers.mesh(lower ^ sample_region),
               helpers.mesh(upper ^ sample_region)]
    sample_transforms = []
    for index, part in enumerate(samples):
        shift = -part.bounds[0] + np.array([index * 60, 0, 0])
        sample_transforms.append(identity + shift.tolist())
    write_3mf(OUT / 'seam-fit-sample.3mf', samples,
              ['lower_seam_sample', 'upper_seam_sample'], sample_transforms)
    report = {
        'crown': 'Continuously tapered egg with a rounded horizontal pole',
        'unit': 'millimeter', 'overall_outer_mm': [224, 180, HEIGHT],
        'lower_shell_top_z_mm': SPLIT,
        'existing_case_bottom_z_mm': FLOOR,
        'existing_case_top_z_mm': FLOOR + 45,
        'wall_nominal_radial_mm': WALL,
        'seam_radial_clearance_mm': .35,
        'seam_vertical_clearance_mm': .25,
        'tongue_depth_below_split_mm': 5.5,
        'source': 'artifacts/enclosure-v1/gesture-bridge-enclosure-v1.3mf',
        'parts': [{'name': name, 'size_mm': part.extents.tolist(),
                   'watertight': bool(part.is_watertight),
                   'connected_bodies': base.body_count(part),
                   'volume_mm3': float(part.volume)}
                  for name, part in zip(names, parts)],
        'boolean_overlap_mm3': {
            'lower_vs_original_case': collision_lower,
            'upper_vs_original_case': collision_upper,
            'upper_vs_lower': collision_seam,
            'inflated_case_envelope': clearance_overlap,
            'storage_proxy_108x92x44': proxy_collision},
        'independent_3mf_import_passed': True,
        'physical_fit_verified': False,
        'full_motion_verified': False,
        'rgb_board_position_verified': False,
        'support_required_upper_dome': True,
        'support_settings_embedded': False,
        'face_engraving_present': HEIGHT > 110,
        'notes': ['Original case is not part of the printable output.',
                  'Cap is removed for operation; no lock or seal is provided.',
                  'Wide front light window is provisional, not a custom LED fit.',
                  'Surface colors require slicer filament assignment.',
                  '2.8 mm inset is radial, not exact normal wall thickness.']}
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2),
                                         encoding='utf-8')
    render(*parts, old)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
