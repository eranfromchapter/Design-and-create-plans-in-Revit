"""The sim's half of the Phase 6 clash law (PLAN.md Part G clash priority) — ONE law
shared with the layout-compiler merge gate (Phase A, oriented shapely prisms) and the
Revit plugin (ElementIntersectsElementFilter with the same exemption pairs):

- walls, doors and windows are NEVER clash elements;
- every other element becomes a 2.5D box: the AABB of its plan footprint plus a z
  range, from catalogs/clash_prisms.json (kind heights, device box, priorities);
- two boxes clash iff they overlap with STRICT inequalities on x, y AND z
  (touching is legal — the Phase 5 placer's model-wide AABB predicate);
- exemption pairs come from the shared table; `pipe_serves_fixture` cannot be
  resolved here (ops carry no served-fixture id) and is deliberately NOT applied —
  branch pipes run below the floor, so they are z-disjoint from furniture anyway;
- run_interference_check scopes the sweep to the envelope's CREATED set x all
  (the plugin's created-set filter); a direct model.apply without an envelope sees
  the all-pairs superset.

The sim's AABBs are a superset of Phase A's oriented prisms: the merge gate's
property test asserts oriented clashes ⊆ AABB clashes with identical exemptions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from revit_sim import placement

if TYPE_CHECKING:  # pragma: no cover — no import cycle at runtime
    from revit_sim.model import Catalogs, SimModel


@dataclass(frozen=True)
class Box:
    element_id: str
    cls: str  # furniture | device | pipe | conduit
    system: str | None
    x0: float
    y0: float
    x1: float
    y1: float
    z0: float
    z1: float


def _aabb(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def family_height_mm(catalogs: Catalogs, revit_family: str, revit_type: str) -> float:
    """Clash height of a placed family = the max kind height its catalog type offers
    (both executors derive it from (family, type), so they agree without `kind`)."""
    heights = catalogs.clash_prisms["kind_heights_mm"]
    kinds = catalogs.family_kinds.get((revit_family, revit_type), ())
    default = float(heights["default"])
    return max((float(heights.get(kind, default)) for kind in kinds), default=default)


def element_boxes(model: SimModel, catalogs: Catalogs) -> list[Box]:
    prisms = catalogs.clash_prisms
    boxes: list[Box] = []
    for fid in sorted(model.families):
        fam = model.families[fid]
        cx, cy = fam["center"]
        w, d = fam["footprint"]
        rad = math.radians(fam["rotation_deg"])
        hx = (abs(w * math.cos(rad)) + abs(d * math.sin(rad))) / 2
        hy = (abs(w * math.sin(rad)) + abs(d * math.cos(rad))) / 2
        height = family_height_mm(catalogs, fam["revit_family"], fam["revit_type"])
        boxes.append(Box(fid, "furniture", None, cx - hx, cy - hy, cx + hx, cy + hy, 0.0, height))
    device_spec = prisms["element_classes"]["device"]
    along = float(device_spec["along_half_mm"])
    z_half = float(device_spec["z_half_mm"])
    for did in sorted(model.devices):
        dev = model.devices[did]
        wall = model.walls[dev["host_wall_id"]]
        start, end = tuple(wall["start"]), tuple(wall["end"])
        fx, fy = placement.centerline_point(start, end, dev["offset"])
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
        half_t = catalogs.wall_thickness_mm.get(wall["revit_type"], 100.0) / 2
        corners = [
            (fx + sa * along * ux + st * half_t * -uy, fy + sa * along * uy + st * half_t * ux)
            for sa in (-1, 1)
            for st in (-1, 1)
        ]
        x0, y0, x1, y1 = _aabb(corners)
        h = float(dev["height_afl"])
        boxes.append(Box(did, "device", None, x0, y0, x1, y1, h - z_half, h + z_half))
    for pid in sorted(model.pipes):
        boxes.extend(_run_boxes(pid, "pipe", model.pipes[pid]))
    for cid in sorted(model.conduits):
        boxes.extend(_run_boxes(cid, "conduit", model.conduits[cid]))
    return boxes


def _run_boxes(element_id: str, cls: str, run: dict[str, Any]) -> list[Box]:
    radius = float(run["diameter"]) / 2
    system = run.get("system")
    out: list[Box] = []
    path = run["path"]
    for a, b in zip(path, path[1:], strict=False):
        x0, y0, x1, y1 = _aabb([(a[0], a[1]), (b[0], b[1])])
        out.append(
            Box(
                element_id,
                cls,
                system,
                x0 - radius,
                y0 - radius,
                x1 + radius,
                y1 + radius,
                min(a[2], b[2]) - radius,
                max(a[2], b[2]) + radius,
            )
        )
    return out


def exempt(a: Box, b: Box, prisms: dict[str, Any]) -> bool:
    for rule in prisms["exempt_pairs"]:
        pair = {rule["a"], rule["b"]}
        classes = {a.cls, b.cls}
        if rule["a"] == rule["b"]:
            if not (a.cls == b.cls == rule["a"]):
                continue
        elif classes != pair:
            continue
        when = rule.get("when")
        if when is None:
            return True
        if when == "same_system":
            return a.system is not None and a.system == b.system
        # pipe_serves_fixture: unresolvable in the sim (see module docstring) -> strict
    return False


def overlaps(a: Box, b: Box) -> bool:
    """Strict inequalities on all three axes: touching is legal."""
    return (
        a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1 and a.z0 < b.z1 and b.z0 < a.z1
    )


def find_clashes(
    boxes: list[Box], created: list[str] | None, prisms: dict[str, Any]
) -> list[tuple[str, str]]:
    """Clashing element pairs in deterministic order: created elements in creation
    order (or all elements sorted when `created` is None) against every OTHER element
    by id; each unordered pair reported once, first-found first."""
    by_id: dict[str, list[Box]] = {}
    for box in boxes:
        by_id.setdefault(box.element_id, []).append(box)
    order = [i for i in created if i in by_id] if created is not None else sorted(by_id)
    seen: set[frozenset[str]] = set()
    clashes: list[tuple[str, str]] = []
    for a_id in order:
        for b_id in sorted(by_id):
            if b_id == a_id or frozenset((a_id, b_id)) in seen:
                continue
            seen.add(frozenset((a_id, b_id)))
            for ba in by_id[a_id]:
                if any(overlaps(ba, bb) and not exempt(ba, bb, prisms) for bb in by_id[b_id]):
                    clashes.append((a_id, b_id))
                    break
    return clashes
