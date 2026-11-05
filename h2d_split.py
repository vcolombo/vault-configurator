"""Split a model across the two H2D nozzles the way Bambu's guide describes.

https://wiki.bambulab.com/en/h2/print-350mm-model-dual-nozzle

The guide says the build plate is 350 mm wide and each nozzle reaches 325 mm. Neither nozzle
can enter the other's restricted strip. A full-width single-material model is cut into parts
of one object ("Cut to parts", with orientation kept), and each part is assigned to one nozzle.

This file uses the reaches already in the printer catalog: the left nozzle is x = 0…325 and
the right nozzle starts at x = 25, so it covers x = 25…350. The shared band is x = 25…325.
The guide does not describe an overlap, a scarf, or a glued pair of separate objects. The cut
here is one vertical plane. The two parts meet on that plane and stay one object.

A part that fits inside either nozzle's 325 × 320 mm reach is not split. A part that only fits
when turned onto the diagonal is not auto-split; the guide's automated case is a straight cut.
Anything wider than 350 mm, or taller than both nozzles can print, is refused.
"""
import math

import numpy as np

# Catalog rows: left bed 325 × 320 at x = 0, right bed 325 wide with origin x = 25.
PLATE_X = 350.0
PLATE_Y = 320.0
LEFT_MAX = 325.0
RIGHT_MIN = 25.0
Z_LIMIT = 320.0  # the left nozzle's Z in the catalog; both nozzles have to print a split part
EPS = 1e-6

MANUAL_STEPS = (
    "This file was not opened in Bambu Studio here, so it is not marked ready to print. "
    "The guide requires the same material in both nozzles (same brand and colour is recommended). "
    "In the slicer, the object should be one body cut into parts: keep orientation, and assign the "
    "left section to the left nozzle and the right section to the right nozzle. "
    "A seam remains on the cut. Supports cannot be given their own nozzle; do not add supports that "
    "land in both the left-only strip and the right-only strip. Multi-colour is not set up by this export."
)


def fit_angle(size, edge=0.0):
    """0 or 90 if the part can sit axis-aligned on the 350 mm plate, else None.

    A diagonal-only fit on one nozzle is left to that nozzle's own row. This mode does not
    turn the 325 mm rectangle into a 350 mm one.
    """
    width, depth, height = size
    if height > Z_LIMIT:
        return None
    bed_x = PLATE_X - 2 * edge
    bed_y = PLATE_Y - 2 * edge
    nozzle_x = LEFT_MAX - 2 * edge
    options = ((0.0, width, depth), (90.0, depth, width))
    for rot, along, across in options:
        if along <= nozzle_x + EPS and across <= bed_y + EPS:
            return rot
    for rot, along, across in options:
        if nozzle_x + EPS < along <= bed_x + EPS and across <= bed_y + EPS:
            return rot
    return None


def _placed_corners(item):
    angle = math.radians(item.get("rot") or 0)
    c, s = math.cos(angle), math.sin(angle)
    width, depth = item["w"], item["d"]
    return [(item["x"] + u * c - v * s, item["y"] + u * s + v * c) for u, v in ((0, 0), (width, 0), (width, depth), (0, depth))]


def annotate_item(item):
    """Mark a packed part single-nozzle or split, from where it actually sits on the plate."""
    xs = [p[0] for p in _placed_corners(item)]
    ys = [p[1] for p in _placed_corners(item)]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    item.pop("splitX", None)
    if min_x < -EPS or max_x > PLATE_X + EPS or min_y < -EPS or max_y > PLATE_Y + EPS:
        item["nozzle"] = "unsplittable"
        return item
    spans_left = min_x < RIGHT_MIN - EPS
    spans_right = max_x > LEFT_MAX + EPS
    if spans_left and spans_right:
        low = max(RIGHT_MIN, min_x)
        high = min(LEFT_MAX, max_x)
        if high - low < 1.0:
            item["nozzle"] = "unsplittable"
            return item
        item["nozzle"] = "split"
        item["splitX"] = round((low + high) / 2.0, 3)
        return item
    item["nozzle"] = "right" if spans_right else "left"
    return item


def annotate_plate(plate):
    for item in plate["items"]:
        annotate_item(item)
    return plate


def place_mesh(tri, x, y, rot):
    """Apply the same Z rotation and translation the 3MF writer uses."""
    out = np.array(tri, dtype=float, copy=True)
    angle = math.radians(rot or 0)
    c, s = math.cos(angle), math.sin(angle)
    u = out[:, :, 0].copy()
    v = out[:, :, 1].copy()
    out[:, :, 0] = x + u * c - v * s
    out[:, :, 1] = y + u * s + v * c
    return out


def _inside(point, plane, keep_left):
    return point[0] <= plane + EPS if keep_left else point[0] >= plane - EPS


def _intersect(a, b, plane):
    da = float(a[0] - plane)
    db = float(b[0] - plane)
    t = da / (da - db)
    return a + (b - a) * t


def _clip(points, plane, keep_left):
    if len(points) == 0:
        return []
    out = []
    prev = points[-1]
    prev_in = _inside(prev, plane, keep_left)
    for cur in points:
        cur_in = _inside(cur, plane, keep_left)
        if cur_in:
            if not prev_in:
                out.append(_intersect(prev, cur, plane))
            out.append(np.asarray(cur, dtype=float))
        elif prev_in:
            out.append(_intersect(prev, cur, plane))
        prev, prev_in = cur, cur_in
    return out


def _key(point):
    return tuple(np.round(point, 4))


def _loops(edges):
    """Directed edges on the cut, as closed loops. None if the cut is not a set of simple loops."""
    nxt = {}
    for start, end in edges:
        ks = _key(start)
        if ks in nxt:
            return None
        nxt[ks] = (_key(end), end, start)
    unused = set(nxt)
    loops = []
    while unused:
        start = next(iter(unused))
        cursor = start
        loop = []
        seen = 0
        while seen <= len(nxt):
            if cursor not in nxt:
                return None
            kend, end, origin = nxt[cursor]
            if not loop:
                loop.append(origin)
            loop.append(end)
            unused.discard(cursor)
            seen += 1
            cursor = kend
            if cursor == start:
                break
        else:
            return None
        loop = loop[:-1]
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _area(loop):
    total = 0.0
    for i, point in enumerate(loop):
        nxt = loop[(i + 1) % len(loop)]
        total += point[1] * nxt[2] - nxt[1] * point[2]
    return total / 2.0


def _ear_clip(loop):
    """Triangulate one planar loop. Returns index triples, or None."""
    if _area(loop) < 0:
        loop = list(reversed(loop))
    pts = np.array([[p[1], p[2]] for p in loop], dtype=float)
    index = list(range(len(loop)))

    def area(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def contains(p, a, b, c):
        ab, bc, ca = area(a, b, p), area(b, c, p), area(c, a, p)
        return (ab >= -1e-9 and bc >= -1e-9 and ca >= -1e-9) or (ab <= 1e-9 and bc <= 1e-9 and ca <= 1e-9)

    tris = []
    guard = 0
    while len(index) > 3 and guard < len(index) * len(index):
        guard += 1
        clipped = False
        for i in range(len(index)):
            i0, i1, i2 = index[i - 1], index[i], index[(i + 1) % len(index)]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if area(a, b, c) <= 1e-10:
                continue
            if any(contains(pts[j], a, b, c) for j in index if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            del index[i]
            clipped = True
            break
        if not clipped:
            return None
    if len(index) == 3:
        a, b, c = pts[index[0]], pts[index[1]], pts[index[2]]
        if abs(area(a, b, c)) <= 1e-10:
            return None
        tris.append(tuple(index))
    return [(loop[i], loop[j], loop[k]) for i, j, k in tris]


def _boundary_count(tri):
    counts = {}
    for triangle in tri:
        for i in range(3):
            a = _key(triangle[i])
            b = _key(triangle[(i + 1) % 3])
            edge = (a, b) if a <= b else (b, a)
            counts[edge] = counts.get(edge, 0) + 1
    return counts


def watertight(tri):
    if len(tri) == 0:
        return False
    return all(count == 2 for count in _boundary_count(tri).values())


def split_mesh(tri, plane):
    """Cut a closed mesh on the vertical plane x = `plane`.

    Returns (left, right) in the same coordinates, or None if the cut cannot be capped.
    The parts meet on the plane. They are not overlapped and not moved apart.
    """
    src = np.asarray(tri, dtype=float)
    if src.size == 0:
        return None
    halves = {True: [], False: []}
    caps = {True: [], False: []}
    for triangle in src:
        if abs(np.linalg.norm(np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0]))) < 1e-12:
            continue
        for keep_left in (True, False):
            poly = _clip(list(triangle), plane, keep_left)
            if len(poly) < 3:
                continue
            for i in range(1, len(poly) - 1):
                halves[keep_left].append(np.stack([poly[0], poly[i], poly[i + 1]]))
            for i in range(len(poly)):
                a, b = poly[i], poly[(i + 1) % len(poly)]
                if abs(a[0] - plane) <= 1e-4 and abs(b[0] - plane) <= 1e-4 and _key(a) != _key(b):
                    caps[keep_left].append((a, b))
    out = []
    for keep_left in (True, False):
        loops = _loops(caps[keep_left])
        if not loops:
            return None
        cap_tris = []
        for loop in loops:
            ears = _ear_clip(loop)
            if not ears:
                return None
            cap_tris.extend(ears)
        body = halves[keep_left]
        if not body or not cap_tris:
            return None
        body_arr = np.stack(body)
        cap_arr = np.stack([np.stack(face) for face in cap_tris])
        # Left of the plane needs a cap whose normal points +X. Right of the plane needs -X.
        normals = np.cross(cap_arr[:, 1] - cap_arr[:, 0], cap_arr[:, 2] - cap_arr[:, 0])
        want = 1.0 if keep_left else -1.0
        if float(normals[:, 0].sum()) * want < 0:
            cap_arr = cap_arr[:, ::-1, :]
        joined = np.concatenate([body_arr, cap_arr])
        if mesh_volume(joined) <= 0 or not watertight(joined):
            return None
        out.append(joined)
    return out[0], out[1]


def mesh_volume(tri):
    tri = np.asarray(tri, dtype=float)
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)


def split_placed(tri, x, y, rot, plane):
    """Place a local mesh, then cut it. None keeps the caller on the unsplit mesh."""
    return split_mesh(place_mesh(tri, x, y, rot), plane)
