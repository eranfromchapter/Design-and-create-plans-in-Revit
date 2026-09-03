"""Canonical SVG plan renderer: deterministic by construction (Phase 1 acceptance —
goldens are compared byte-for-byte). Fixed element sort (kind, then id), fixed
attribute order, 1-decimal-mm rounding, stable ids. Never reformat casually: the
golden fixtures pin these bytes."""

from __future__ import annotations

import math

from revit_sim import clash
from revit_sim.model import Catalogs, SimModel

MARGIN = 250.0


PIPE_COLOURS = {
    "sanitary": "#1f4e9c",
    "vent": "#2e8b57",
    "supply_h": "#c0392b",
    "supply_c": "#1f9cc0",
}
DEVICE_RADIUS = 60.0


def _is_vertical(path: list[list[float]]) -> bool:
    """A stack: two or more points sharing one plan position (within 0.05mm)."""
    if len(path) < 2:
        return False
    x0, y0 = path[0][0], path[0][1]
    return all(abs(x - x0) <= 0.05 and abs(y - y0) <= 0.05 for x, y, _z in path)


def _device_symbol(device_id: str, kind: str, x: float, y: float) -> str:
    """Plan symbols per device kind (NEC-style): receptacle = circle + tick, gfci =
    circle + filled square, receptacle_240 = double ring, switch = square + diagonal."""
    r = DEVICE_RADIUS
    head = f'<g class="device {kind}" data-id="{device_id}">'
    if kind == "switch":
        body = (
            f'<rect x="{_f(x - 50)}" y="{_f(y - 50)}" width="100.0" height="100.0" '
            f'fill="white" stroke="black" stroke-width="15.0"/>'
            f'<line x1="{_f(x - 50)}" y1="{_f(y + 50)}" x2="{_f(x + 50)}" y2="{_f(y - 50)}" '
            f'stroke="black" stroke-width="15.0"/>'
        )
    else:
        body = (
            f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{_f(r)}" fill="white" stroke="black" '
            f'stroke-width="15.0"/>'
        )
        if kind == "gfci":
            body += (
                f'<rect x="{_f(x - 25)}" y="{_f(y - 25)}" width="50.0" height="50.0" fill="black"/>'
            )
        elif kind == "receptacle_240":
            body += (
                f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{_f(r / 2)}" fill="none" stroke="black" '
                f'stroke-width="15.0"/>'
            )
        else:  # receptacle
            body += (
                f'<line x1="{_f(x - r)}" y1="{_f(y)}" x2="{_f(x + r)}" y2="{_f(y)}" '
                f'stroke="black" stroke-width="15.0"/>'
            )
    return head + body + "</g>"


def _f(v: float) -> str:
    return f"{v:.1f}"


def render_plan(model: SimModel) -> str:
    xs: list[float] = []
    ys: list[float] = []
    for wall in model.walls.values():
        xs += [wall["start"][0], wall["end"][0]]
        ys += [wall["start"][1], wall["end"][1]]
    for fam in model.families.values():
        xs.append(fam["center"][0])
        ys.append(fam["center"][1])
    # Phase 6 MEP elements extend the viewBox only when present (goldens 1-5 unchanged)
    for device in model.devices.values():
        xs.append(device["point"][0])
        ys.append(device["point"][1])
    for run in (*model.pipes.values(), *model.conduits.values()):
        for x, y, _z in run["path"]:
            xs.append(x)
            ys.append(y)
    if not xs:
        xs, ys = [0.0], [0.0]
    min_x, max_x = min(xs) - MARGIN, max(xs) + MARGIN
    min_y, max_y = min(ys) - MARGIN, max(ys) + MARGIN

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_f(min_x)} {_f(min_y)} '
        f'{_f(max_x - min_x)} {_f(max_y - min_y)}">'
    )

    # demolished elements render dashed (Phase 4 review cards / phase-new plans);
    # standing elements keep their exact pre-Phase-4 bytes — goldens stay valid
    for wall_id in sorted(model.walls):
        wall = model.walls[wall_id]
        demolished = wall_id in model.demolished
        state = "demolished" if demolished else "standing"
        dash = ' stroke-dasharray="240.0 120.0"' if demolished else ""
        parts.append(
            f'<line class="wall {state}" data-id="{wall_id}" '
            f'x1="{_f(wall["start"][0])}" y1="{_f(wall["start"][1])}" '
            f'x2="{_f(wall["end"][0])}" y2="{_f(wall["end"][1])}" '
            f'stroke="black" stroke-width="100.0"{dash}/>'
        )
    for door_id in sorted(model.doors):
        x, y, _ = model.doors[door_id]["point"]
        width = model.doors[door_id]["width"]
        demolished = door_id in model.demolished
        cls = "door demolished" if demolished else "door"
        dash = ' stroke-dasharray="80.0 40.0"' if demolished else ""
        parts.append(
            f'<circle class="{cls}" data-id="{door_id}" cx="{_f(x)}" cy="{_f(y)}" '
            f'r="{_f(width / 2)}" fill="white" stroke="black" stroke-width="20.0"{dash}/>'
        )
    for window_id in sorted(model.windows):
        x, y, _ = model.windows[window_id]["point"]
        width = model.windows[window_id]["width"]
        demolished = window_id in model.demolished
        cls = "window demolished" if demolished else "window"
        dash = ' stroke-dasharray="80.0 40.0"' if demolished else ""
        parts.append(
            f'<rect class="{cls}" data-id="{window_id}" x="{_f(x - width / 2)}" '
            f'y="{_f(y - 50)}" width="{_f(width)}" height="100.0" '
            f'fill="white" stroke="black" stroke-width="20.0"{dash}/>'
        )
    for family_id in sorted(model.families):
        fam = model.families[family_id]
        cx, cy = fam["center"]
        w, d = fam["footprint"]
        parts.append(
            f'<rect class="family" data-id="{family_id}" x="{_f(cx - w / 2)}" '
            f'y="{_f(cy - d / 2)}" width="{_f(w)}" height="{_f(d)}" '
            f'transform="rotate({_f(fam["rotation_deg"])} {_f(cx)} {_f(cy)})" '
            f'fill="none" stroke="grey" stroke-width="20.0"/>'
        )
    # ---- Phase 6 MEP symbols (append-only; classes are the review-card legend) ----
    for device_id in sorted(model.devices):
        device = model.devices[device_id]
        x, y, _ = device["point"]
        parts.append(_device_symbol(device_id, device["kind"], x, y))
    for pipe_id in sorted(model.pipes):
        pipe = model.pipes[pipe_id]
        colour = PIPE_COLOURS.get(pipe["system"], "#1f4e9c")
        if _is_vertical(pipe["path"]):
            # a stack: the plan sees a circle with a cross at the riser position
            x, y, _ = pipe["path"][0]
            radius = pipe["diameter"] / 2 + 40.0
            parts.append(
                f'<g class="stack {pipe["system"]}" data-id="{pipe_id}">'
                f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{_f(radius)}" fill="white" '
                f'stroke="{colour}" stroke-width="15.0"/>'
                f'<line x1="{_f(x - radius)}" y1="{_f(y)}" x2="{_f(x + radius)}" y2="{_f(y)}" '
                f'stroke="{colour}" stroke-width="15.0"/>'
                f'<line x1="{_f(x)}" y1="{_f(y - radius)}" x2="{_f(x)}" y2="{_f(y + radius)}" '
                f'stroke="{colour}" stroke-width="15.0"/></g>'
            )
            continue
        pts = " ".join(f"{_f(x)},{_f(y)}" for x, y, _z in pipe["path"])
        parts.append(
            f'<polyline class="pipe {pipe["system"]}" data-id="{pipe_id}" points="{pts}" '
            f'fill="none" stroke="{colour}" stroke-width="{_f(max(pipe["diameter"], 20.0))}" '
            f'stroke-linejoin="round"/>'
        )
    for conduit_id in sorted(model.conduits):
        pts = " ".join(f"{_f(x)},{_f(y)}" for x, y, _z in model.conduits[conduit_id]["path"])
        parts.append(
            f'<polyline class="conduit" data-id="{conduit_id}" points="{pts}" fill="none" '
            f'stroke="#e08a00" stroke-width="20.0" stroke-dasharray="120.0 60.0"/>'
        )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# ---- Phase 7: section + axonometric renderers (append-only; docs/PHASE7_DESIGN.md P7-11) ----
# Both take the catalogs because wall thickness and kind heights live there (the same rules
# as revit_sim.clash). render_plan above is untouched: goldens 1-6 stay byte-stable.

CUT_EPS = 0.05  # the same plan-position tolerance as _is_vertical
AXON_COS = 0.8660254037844386  # cos 30 deg
AXON_SIN = 0.5  # sin 30 deg
STROKE_WALL = 20.0
STROKE_FAMILY = 20.0
DEFAULT_HEIGHT = 2700.0


def _wall_thickness(wall: dict, catalogs: Catalogs) -> float:
    """The merge gate / clash rule: scanned as-built thickness wins over the catalog."""
    return float(
        wall.get("as_built_thickness") or catalogs.wall_thickness_mm.get(wall["revit_type"], 100.0)
    )


def _unit(start: list[float], end: list[float]) -> tuple[float, float, float]:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return 1.0, 0.0, 0.0
    return dx / length, dy / length, length


def _signed_area(corners: list[tuple[float, float]]) -> float:
    area = 0.0
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1], strict=True):
        area += x0 * y1 - x1 * y0
    return area / 2


def _wall_slab(wall: dict, thickness: float) -> list[tuple[float, float]]:
    """The wall's footprint rectangle (4 corners, counter-clockwise)."""
    sx, sy = wall["start"]
    ex, ey = wall["end"]
    ux, uy, _ = _unit(wall["start"], wall["end"])
    nx, ny = -uy, ux
    h = thickness / 2
    corners = [
        (sx + nx * h, sy + ny * h),
        (ex + nx * h, ey + ny * h),
        (ex - nx * h, ey - ny * h),
        (sx - nx * h, sy - ny * h),
    ]
    if _signed_area(corners) < 0:
        corners.reverse()
    return corners


def _family_corners(fam: dict) -> list[tuple[float, float]]:
    """The rotated footprint (the same rotation matrix as render_plan's `rotate`), CCW."""
    cx, cy = fam["center"]
    w, d = fam["footprint"]
    rad = math.radians(fam["rotation_deg"])
    c, s = math.cos(rad), math.sin(rad)
    local = [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)]
    corners = [(cx + lx * c - ly * s, cy + lx * s + ly * c) for lx, ly in local]
    if _signed_area(corners) < 0:
        corners.reverse()
    return corners


def _family_height(fam: dict, catalogs: Catalogs) -> float:
    return clash.family_height_mm(catalogs, fam["revit_family"], fam["revit_type"])


def _plan_extents(model: SimModel) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for wall in model.walls.values():
        xs += [wall["start"][0], wall["end"][0]]
        ys += [wall["start"][1], wall["end"][1]]
    for fam in model.families.values():
        xs.append(fam["center"][0])
        ys.append(fam["center"][1])
    if not xs:
        xs, ys = [0.0], [0.0]
    return xs, ys


def _run_polyline_xz(run_id: str, cls: str, run: dict, extra: str) -> str:
    pts = " ".join(f"{_f(x)},{_f(-z)}" for x, _y, z in run["path"])
    return f'<polyline class="{cls}" data-id="{run_id}" points="{pts}" fill="none" {extra}/>'


def render_section(model: SimModel, catalogs: Catalogs) -> str:
    """Elevation through the model's bbox centre looking +Y (screen u = x, v = z; SVG y = -z).
    Walls entirely at/beyond the cut are elevation rectangles with their door/window
    openings; walls crossing the cut are filled cut rectangles (an opening containing the
    crossing is drawn white); walls behind the cut are omitted. Families are boxes at their
    catalog kind height, devices sit on drawn hosts, pipes/conduits at/beyond the cut are
    (x, z) polylines. Deterministic: canonical order, 1-decimal formatting."""
    xs, ys = _plan_extents(model)
    yc = (min(ys) + max(ys)) / 2
    z_top = DEFAULT_HEIGHT
    z_bot = 0.0
    for wall in model.walls.values():
        z_top = max(z_top, float(wall["height"]))
    for fam in model.families.values():
        z_top = max(z_top, _family_height(fam, catalogs))
    for run in (*model.pipes.values(), *model.conduits.values()):
        for _x, _y, z in run["path"]:
            z_top = max(z_top, z)
            z_bot = min(z_bot, z)
    min_x, max_x = min(xs) - MARGIN, max(xs) + MARGIN
    top, bottom = -(z_top + MARGIN), -z_bot + MARGIN

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_f(min_x)} {_f(top)} '
        f'{_f(max_x - min_x)} {_f(bottom - top)}">',
        f'<line class="ground" x1="{_f(min_x)}" y1="0.0" x2="{_f(max_x)}" y2="0.0" '
        f'stroke="black" stroke-width="10.0"/>',
    ]

    elevation: list[tuple[float, str]] = []
    cut: list[str] = []
    for wall_id in sorted(model.walls):
        wall = model.walls[wall_id]
        lo = min(wall["start"][1], wall["end"][1])
        hi = max(wall["start"][1], wall["end"][1])
        if lo >= yc - CUT_EPS:
            elevation.append((-lo, wall_id))  # far first
        elif lo < yc - CUT_EPS and hi > yc + CUT_EPS:
            cut.append(wall_id)
    elevation.sort()
    drawn_hosts: set[str] = set()

    def openings_of(wall_id: str) -> list[tuple[str, str, dict]]:
        out = [("door", d, model.doors[d]) for d in sorted(model.doors)]
        out += [("window", n, model.windows[n]) for n in sorted(model.windows)]
        return [(k, i, o) for k, i, o in out if o["host_wall_id"] == wall_id]

    def dash_for(element_id: str) -> str:
        return ' stroke-dasharray="240.0 120.0"' if element_id in model.demolished else ""

    for _key, wall_id in elevation:
        wall = model.walls[wall_id]
        drawn_hosts.add(wall_id)
        corners = _wall_slab(wall, _wall_thickness(wall, catalogs))
        x0 = min(x for x, _ in corners)
        x1 = max(x for x, _ in corners)
        height = float(wall["height"])
        parts.append(
            f'<rect class="wall elevation" data-id="{wall_id}" x="{_f(x0)}" y="{_f(-height)}" '
            f'width="{_f(x1 - x0)}" height="{_f(height)}" fill="white" stroke="black" '
            f'stroke-width="{_f(STROKE_WALL)}"{dash_for(wall_id)}/>'
        )
        ux, _uy, _ = _unit(wall["start"], wall["end"])
        for kind, opening_id, opening in openings_of(wall_id):
            half = opening["width"] / 2 * abs(ux)
            if half < 1.0:
                continue  # wall edge-on to the viewer: the opening has no width on screen
            px = opening["point"][0]
            ox0, ox1 = max(x0, px - half), min(x1, px + half)
            if ox1 <= ox0:
                continue
            if kind == "door":
                oy, oh = -float(opening["height"]), float(opening["height"])
            else:
                sill = float(opening["sill_height"])
                oy, oh = -(sill + float(opening["height"])), float(opening["height"])
            parts.append(
                f'<rect class="opening {kind}" data-id="{opening_id}" x="{_f(ox0)}" '
                f'y="{_f(oy)}" width="{_f(ox1 - ox0)}" height="{_f(oh)}" fill="white" '
                f'stroke="black" stroke-width="{_f(STROKE_WALL)}"{dash_for(opening_id)}/>'
            )

    for wall_id in cut:
        wall = model.walls[wall_id]
        drawn_hosts.add(wall_id)
        corners = _wall_slab(wall, _wall_thickness(wall, catalogs))
        crossings: list[float] = []
        for (px0, py0), (px1, py1) in zip(corners, corners[1:] + corners[:1], strict=True):
            if py0 == py1 or (py0 - yc) * (py1 - yc) > 0:
                continue
            crossings.append(px0 + (yc - py0) * (px1 - px0) / (py1 - py0))
        if len(crossings) < 2:
            continue
        x0, x1 = min(crossings), max(crossings)
        height = float(wall["height"])
        parts.append(
            f'<rect class="wall cut" data-id="{wall_id}" x="{_f(x0)}" y="{_f(-height)}" '
            f'width="{_f(x1 - x0)}" height="{_f(height)}" fill="black"/>'
        )
        ux, uy, _ = _unit(wall["start"], wall["end"])
        xm = (x0 + x1) / 2
        along = (xm - wall["start"][0]) * ux + (yc - wall["start"][1]) * uy
        for kind, opening_id, opening in openings_of(wall_id):
            w = opening["width"]
            if not (opening["offset"] - w / 2 <= along <= opening["offset"] + w / 2):
                continue
            if kind == "door":
                oy, oh = -float(opening["height"]), float(opening["height"])
            else:
                sill = float(opening["sill_height"])
                oy, oh = -(sill + float(opening["height"])), float(opening["height"])
            parts.append(
                f'<rect class="opening {kind} cut" data-id="{opening_id}" x="{_f(x0)}" '
                f'y="{_f(oy)}" width="{_f(x1 - x0)}" height="{_f(oh)}" fill="white"/>'
            )

    for family_id in sorted(model.families):
        fam = model.families[family_id]
        corners = _family_corners(fam)
        if max(y for _, y in corners) < yc - CUT_EPS:
            continue  # entirely behind the cut
        x0 = min(x for x, _ in corners)
        x1 = max(x for x, _ in corners)
        height = _family_height(fam, catalogs)
        parts.append(
            f'<rect class="family" data-id="{family_id}" x="{_f(x0)}" y="{_f(-height)}" '
            f'width="{_f(x1 - x0)}" height="{_f(height)}" fill="none" stroke="grey" '
            f'stroke-width="{_f(STROKE_FAMILY)}"/>'
        )

    device_spec = catalogs.clash_prisms.get("element_classes", {}).get("device", {})
    along_half = float(device_spec.get("along_half_mm", 50.0))
    z_half = float(device_spec.get("z_half_mm", 60.0))
    for device_id in sorted(model.devices):
        device = model.devices[device_id]
        if device["host_wall_id"] not in drawn_hosts:
            continue
        x, _y, _ = device["point"]
        h = float(device["height_afl"])
        parts.append(
            f'<rect class="device {device["kind"]}" data-id="{device_id}" '
            f'x="{_f(x - along_half)}" y="{_f(-(h + z_half))}" width="{_f(2 * along_half)}" '
            f'height="{_f(2 * z_half)}" fill="white" stroke="black" stroke-width="15.0"/>'
        )

    for pipe_id in sorted(model.pipes):
        pipe = model.pipes[pipe_id]
        if max(y for _x, y, _z in pipe["path"]) < yc - CUT_EPS:
            continue
        colour = PIPE_COLOURS.get(pipe["system"], "#1f4e9c")
        parts.append(
            _run_polyline_xz(
                pipe_id,
                f"pipe {pipe['system']}",
                pipe,
                f'stroke="{colour}" stroke-width="{_f(max(pipe["diameter"], 20.0))}" '
                'stroke-linejoin="round"',
            )
        )
    for conduit_id in sorted(model.conduits):
        conduit = model.conduits[conduit_id]
        if max(y for _x, y, _z in conduit["path"]) < yc - CUT_EPS:
            continue
        parts.append(
            _run_polyline_xz(
                conduit_id,
                "conduit",
                conduit,
                'stroke="#e08a00" stroke-width="20.0" stroke-dasharray="120.0 60.0"',
            )
        )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _project(x: float, y: float, z: float) -> tuple[float, float]:
    """30-degree axonometric: viewer at (-inf, -inf, +inf); +x right, +y left, +z up."""
    return (x - y) * AXON_COS, -((x + y) * AXON_SIN + z)


def render_axon(model: SimModel, catalogs: Catalogs) -> str:
    """The sim's "3d_hidden": every wall slab and family footprint as a box drawn in
    painter's order (far = larger x+y first) with only its viewer-facing side faces and its
    top, filled white — a cheap hidden-surface look, NO true hidden-line removal
    (documented deviation D-3). Deterministic: canonical order, 1-decimal formatting."""
    boxes: list[tuple[tuple[float, str], str, str, list[tuple[float, float]], float, str]] = []
    for wall_id in sorted(model.walls):
        wall = model.walls[wall_id]
        corners = _wall_slab(wall, _wall_thickness(wall, catalogs))
        cx = sum(x for x, _ in corners) / 4
        cy = sum(y for _, y in corners) / 4
        height = float(wall["height"])
        boxes.append(((-(cx + cy), wall_id), wall_id, "wall", corners, height, "black"))
    for family_id in sorted(model.families):
        fam = model.families[family_id]
        corners = _family_corners(fam)
        cx, cy = fam["center"]
        height = _family_height(fam, catalogs)
        boxes.append(((-(cx + cy), family_id), family_id, "family", corners, height, "grey"))
    boxes.sort(key=lambda b: b[0])

    us: list[float] = []
    vs: list[float] = []
    polys: list[str] = []
    for _key, element_id, cls, corners, height, stroke in boxes:
        faces: list[list[tuple[float, float]]] = []
        for (px, py), (qx, qy) in zip(corners, corners[1:] + corners[:1], strict=True):
            ex, ey = qx - px, qy - py
            # outward normal of a CCW polygon edge = (ey, -ex); visible iff it faces (-1, -1)
            if -ey + ex <= 1e-9:
                continue
            faces.append([(px, py, 0.0), (qx, qy, 0.0), (qx, qy, height), (px, py, height)])
        faces.append([(x, y, height) for x, y in corners])
        group = [f'<g class="box {cls}" data-id="{element_id}">']
        for face in faces:
            pts = [_project(*p) for p in face]
            us += [u for u, _ in pts]
            vs += [v for _, v in pts]
            points = " ".join(f"{_f(u)},{_f(v)}" for u, v in pts)
            group.append(
                f'<polygon points="{points}" fill="white" stroke="{stroke}" '
                f'stroke-width="{_f(STROKE_WALL)}"/>'
            )
        group.append("</g>")
        polys.append("".join(group))
    if not us:
        us, vs = [0.0], [0.0]
    min_u, max_u = min(us) - MARGIN, max(us) + MARGIN
    min_v, max_v = min(vs) - MARGIN, max(vs) + MARGIN
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_f(min_u)} {_f(min_v)} '
        f'{_f(max_u - min_u)} {_f(max_v - min_v)}">',
        *polys,
        "</svg>",
    ]
    return "\n".join(parts) + "\n"
