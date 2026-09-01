"""Canonical SVG plan renderer: deterministic by construction (Phase 1 acceptance —
goldens are compared byte-for-byte). Fixed element sort (kind, then id), fixed
attribute order, 1-decimal-mm rounding, stable ids. Never reformat casually: the
golden fixtures pin these bytes."""

from __future__ import annotations

from revit_sim.model import SimModel

MARGIN = 250.0


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
    for device_id in sorted(model.devices):
        x, y, _ = model.devices[device_id]["point"]
        parts.append(
            f'<circle class="device {model.devices[device_id]["kind"]}" data-id="{device_id}" '
            f'cx="{_f(x)}" cy="{_f(y)}" r="60.0" fill="black"/>'
        )
    for pipe_id in sorted(model.pipes):
        pts = " ".join(f"{_f(x)},{_f(y)}" for x, y, _z in model.pipes[pipe_id]["path"])
        parts.append(
            f'<polyline class="pipe {model.pipes[pipe_id]["system"]}" data-id="{pipe_id}" '
            f'points="{pts}" fill="none" stroke="blue" stroke-width="30.0"/>'
        )
    for conduit_id in sorted(model.conduits):
        pts = " ".join(f"{_f(x)},{_f(y)}" for x, y, _z in model.conduits[conduit_id]["path"])
        parts.append(
            f'<polyline class="conduit" data-id="{conduit_id}" points="{pts}" '
            f'fill="none" stroke="orange" stroke-width="20.0"/>'
        )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
