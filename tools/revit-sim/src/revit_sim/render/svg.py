"""Canonical SVG plan renderer: deterministic by construction (Phase 1 acceptance —
goldens are compared byte-for-byte). Fixed element sort (kind, then id), fixed
attribute order, 1-decimal-mm rounding, stable ids. Never reformat casually: the
golden fixtures pin these bytes."""

from __future__ import annotations

from revit_sim.model import SimModel

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
