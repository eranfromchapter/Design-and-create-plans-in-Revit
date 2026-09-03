"""Element -> 2.5D prism (docs/PHASE6_DESIGN.md §4.2, PIN-24/25): oriented plan
polygon + z range + priority class, from the furnished layout (furniture, columns,
risers) and the MEP ops (pipes, devices, conduits). Walls/doors/windows are never
clash elements. Heights, the device box, the riser radius and the exemption pairs
come from catalogs/clash_prisms.json — the same file revit-sim and the plugin read.
Unlike the sim, Phase A can resolve `pipe_serves_fixture` (segments carry their
fixture ids) and uses ORIENTED polygons; the sim's AABBs are a superset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, Point, Polygon, box

from layout_compiler.catalogs import clash_prisms, family_types, wall_thickness_mm
from layout_compiler.geometry import furniture_rect, pt_on_wall
from layout_compiler.mep.inputs import left_normal, unit_along


@dataclass(frozen=True)
class Prism:
    element_id: str
    cls: str  # structure | pipe | conduit | device | furniture
    priority: int
    system: str | None
    polygon: Polygon
    z0: float
    z1: float
    serves: frozenset[str] = frozenset()  # pipe segments: fixture ids they drain

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.element_id, "cls": self.cls, "priority": self.priority}


def _prio(cls: str, system: str | None) -> int:
    """Element class -> clash class (catalogs/clash_prisms.json element_classes) ->
    priority: structure 0, sanitary/vent 1, supply 2, hvac 3, electrical 4, furniture 5."""
    spec = clash_prisms()
    element = "riser" if cls == "structure" else cls
    klass = spec["element_classes"][element]["class"]
    if klass == "by_system":
        klass = system or "sanitary"
    return int(spec["priorities"][klass])


def family_height(revit_family: str, revit_type: str) -> float:
    heights = clash_prisms()["kind_heights_mm"]
    spec = family_types().get((revit_family, revit_type))
    kinds = spec["kinds"] if spec else ()
    default = float(heights["default"])
    return max((float(heights.get(k, default)) for k in kinds), default=default)


def _run_prisms(
    element_id: str, cls: str, run: dict[str, Any], serves: frozenset[str]
) -> list[Prism]:
    radius = float(run["diameter"]) / 2
    system = run.get("system")
    out: list[Prism] = []
    path = run["path"]
    for a, b in zip(path, path[1:], strict=False):
        if abs(a[0] - b[0]) <= 0.05 and abs(a[1] - b[1]) <= 0.05:
            poly = Point(a[0], a[1]).buffer(radius, quad_segs=8)
        else:
            poly = LineString([(a[0], a[1]), (b[0], b[1])]).buffer(radius, quad_segs=8)
        out.append(
            Prism(
                element_id,
                cls,
                _prio(cls, system),
                system,
                poly,
                min(a[2], b[2]) - radius,
                max(a[2], b[2]) + radius,
                serves,
            )
        )
    return out


def build_prisms(
    layout: dict[str, Any],
    mep_ops: list[dict[str, Any]],
    branch_fixtures: dict[str, list[str]] | None = None,
) -> list[Prism]:
    """`layout` is the furnished layout with meta.levels stamped; `mep_ops` the MEP
    half (create_pipe / place_device / create_conduit); `branch_fixtures` maps pipe
    ids to the fixture ids they serve (from the MepPlan branches)."""
    spec = clash_prisms()
    levels = layout["meta"].get("levels") or {}
    floor_z = float(levels.get("floor_z", 0.0))
    ceiling_z = float(levels.get("ceiling_z", 2700.0))
    slab = float(levels.get("slab_to_slab", ceiling_z - floor_z))
    h_plenum = slab - (ceiling_z - floor_z)
    walls = {w["id"]: w for w in layout["walls"]}
    thickness = wall_thickness_mm()
    serves = branch_fixtures or {}
    prisms: list[Prism] = []
    for entry in layout.get("furniture", []):
        for item in sorted(entry["items"], key=lambda i: i["id"]):
            prisms.append(
                Prism(
                    item["id"],
                    "furniture",
                    _prio("furniture", None),
                    None,
                    furniture_rect(item),
                    floor_z,
                    floor_z + family_height(item["revit_family"], item["revit_type"]),
                )
            )
    for col in sorted(layout.get("columns") or [], key=lambda c: c["id"]):
        cx, cy = col["center"]
        size = col.get("size") or col.get("footprint") or [300.0, 300.0]
        prisms.append(
            Prism(
                col["id"],
                "structure",
                _prio("structure", None),
                None,
                box(cx - size[0] / 2, cy - size[1] / 2, cx + size[0] / 2, cy + size[1] / 2),
                floor_z,
                ceiling_z,
            )
        )
    riser_r = float(spec["element_classes"]["riser"]["radius_mm"])
    for riser in sorted(layout.get("risers") or [], key=lambda r: r["id"]):
        prisms.append(
            Prism(
                riser["id"],
                "structure",
                _prio("structure", None),
                None,
                Point(riser["center"][0], riser["center"][1]).buffer(riser_r, quad_segs=8),
                floor_z - h_plenum,
                ceiling_z,
            )
        )
    dev_spec = spec["element_classes"]["device"]
    along, z_half = float(dev_spec["along_half_mm"]), float(dev_spec["z_half_mm"])
    for op in mep_ops:
        args = op["args"]
        if op["op"] == "create_pipe":
            served = frozenset(serves.get(args["id"], []))
            prisms.extend(_run_prisms(args["id"], "pipe", args, served))
        elif op["op"] == "create_conduit":
            prisms.extend(_run_prisms(args["id"], "conduit", args, frozenset()))
        elif op["op"] == "place_device":
            wall = walls[args["host_wall_id"]]
            fx, fy = pt_on_wall(wall, args["offset"])
            ux, uy = unit_along(wall)
            nx, ny = left_normal(wall)
            t = thickness.get(wall["revit_type"], float(wall.get("as_built_thickness") or 100.0))
            if wall.get("as_built_thickness"):
                t = float(wall["as_built_thickness"])
            corners = [
                (fx + sa * along * ux + st * (t / 2) * nx, fy + sa * along * uy + st * (t / 2) * ny)
                for sa, st in ((-1, -1), (1, -1), (1, 1), (-1, 1))
            ]
            h = floor_z + float(args["height_afl"])  # absolute, like the pipe/conduit z
            prisms.append(
                Prism(
                    args["id"],
                    "device",
                    _prio("device", None),
                    None,
                    Polygon(corners),
                    h - z_half,
                    h + z_half,
                )
            )
    return prisms
