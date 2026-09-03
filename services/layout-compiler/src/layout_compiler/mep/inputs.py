"""MEP inputs (docs/PHASE6_DESIGN.md §2.2, PIN-01..04, 18, 33): levels and panel
resolution with stamping into meta, wet rooms, fixtures (catalog semantics by
`kind` — never family names), host walls (placer-recorded first), counter walls
(casework `is_counter`, sink/dishwasher fallback when the layout has no casework),
outlet spacing, and the blocking/info review items each of them can raise."""

from __future__ import annotations

import copy
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Point, Polygon

from layout_compiler.catalogs import drain_slope, plumbing_table
from layout_compiler.geometry import furniture_rect, pt_on_wall, wall_len, wall_thickness_of
from layout_compiler.mep.constants import (
    E1_DEFAULT_SPACING_MM,
    E1_MIN_OUTLET_SPACING_MM,
    E2_COUNTER_FALLBACK_EXTEND_MM,
    PANEL_MAX_WALL_DIST_MM,
    SLAB_TO_SLAB_MAX_MM,
    SLAB_TO_SLAB_MIN_MM,
)

DeadlineCheck = Callable[[], None] | None

SI8_FLAGS = ("is_demising", "is_load_bearing", "is_exterior")
COUNTER_APPLIANCE_KINDS = ("range", "oven", "refrigerator")
COUNTER_FIXTURE_KINDS = ("kitchen_sink", "dishwasher")


class MepError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class ReviewItem:
    code: str
    severity: str  # "blocking" | "info"
    refs: list[str]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "refs": list(self.refs),
            "message": self.message,
        }


@dataclass
class Fixture:
    item: dict[str, Any]
    room_id: str
    host_wall_id: str
    kind: str
    fixture_units: float
    drain_mm: float
    slope: float

    @property
    def id(self) -> str:
        return str(self.item["id"])

    @property
    def center(self) -> tuple[float, float]:
        return (float(self.item["center"][0]), float(self.item["center"][1]))


@dataclass
class MepInputs:
    layout: dict[str, Any]
    walls: dict[str, dict[str, Any]]
    rooms: dict[str, dict[str, Any]]
    polygons: dict[str, Polygon]
    floor_z: float
    ceiling_z: float
    slab_to_slab: float | None
    h_plenum: float | None
    h_fitting: float
    levels_source: str
    panel: tuple[float, float] | None
    panel_source: str
    panel_node: tuple[float, float] | None
    panel_wall_id: str | None
    outlet_spacing: float
    wet_rooms: list[str]
    derived_wet_rooms: list[str]
    counter_walls: dict[str, list[str]]
    counter_source: str
    counter_runs: dict[tuple[str, str], list[tuple[float, float]]]
    fixtures: list[Fixture]
    host_walls: dict[str, str]
    items: list[ReviewItem] = field(default_factory=list)

    def blocking(self) -> list[str]:
        return sorted({i.code for i in self.items if i.severity == "blocking"})

    def summary(self) -> dict[str, Any]:
        return {
            "floor_z": self.floor_z,
            "ceiling_z": self.ceiling_z,
            "slab_to_slab": self.slab_to_slab,
            "h_plenum": self.h_plenum,
            "h_fitting": self.h_fitting,
            "levels_source": self.levels_source,
            "panel": list(self.panel) if self.panel else None,
            "panel_source": self.panel_source,
            "panel_node": list(self.panel_node) if self.panel_node else None,
            "panel_wall_id": self.panel_wall_id,
            "outlet_spacing": self.outlet_spacing,
            "wet_rooms": list(self.wet_rooms),
            "derived_wet_rooms": list(self.derived_wet_rooms),
            "counter_walls": {k: list(v) for k, v in sorted(self.counter_walls.items())},
            "counter_source": self.counter_source,
            "host_walls": dict(sorted(self.host_walls.items())),
        }


# ---- geometry helpers ------------------------------------------------------------


def unit_along(wall: dict[str, Any]) -> tuple[float, float]:
    length = wall_len(wall)
    if length == 0:
        return (1.0, 0.0)
    return (
        (wall["end"][0] - wall["start"][0]) / length,
        (wall["end"][1] - wall["start"][1]) / length,
    )


def left_normal(wall: dict[str, Any]) -> tuple[float, float]:
    ux, uy = unit_along(wall)
    return (-uy, ux)


def offset_of(point: tuple[float, float], wall: dict[str, Any]) -> float:
    """Signed offset of a point's projection along the wall from its start (mm)."""
    ux, uy = unit_along(wall)
    return (point[0] - wall["start"][0]) * ux + (point[1] - wall["start"][1]) * uy


def wall_line(wall: dict[str, Any]) -> LineString:
    return LineString([tuple(wall["start"]), tuple(wall["end"])])


def wall_thickness(wall: dict[str, Any]) -> float:
    return float(wall_thickness_of(wall) or 0.0)


def placed_items(layout: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (entry["room_id"], item) for entry in layout.get("furniture", []) for item in entry["items"]
    ]


# ---- resolution ------------------------------------------------------------------


def _resolve_host_wall(
    item: dict[str, Any],
    room: dict[str, Any],
    walls: dict[str, dict[str, Any]],
    recorded: str | None,
) -> str:
    """PIN-03: placer-recorded wall if it bounds the room; else the boundary wall whose
    centerline distance equals t/2 + (item extent across the wall)/2 within 1 mm; else
    the nearest centerline; ties -> smaller id."""
    boundary = list(room["boundary_wall_ids"])
    if recorded in boundary:
        return recorded
    center = Point(item["center"])
    rect = furniture_rect(item)
    scored: list[tuple[float, str]] = []
    nearest: list[tuple[float, str]] = []
    for wall_id in sorted(boundary):
        wall = walls[wall_id]
        line = wall_line(wall)
        dist = line.distance(center)
        nx, ny = left_normal(wall)
        projections = [cx * nx + cy * ny for cx, cy in rect.exterior.coords[:4]]
        extent = max(projections) - min(projections)
        expected = wall_thickness(wall) / 2 + extent / 2
        scored.append((abs(dist - expected), wall_id))
        nearest.append((dist, wall_id))
    scored.sort()
    if scored and scored[0][0] <= 1.0:
        return scored[0][1]
    nearest.sort()
    return nearest[0][1]


def _resolve_levels(
    layout: dict[str, Any],
    commit0_layout: dict[str, Any],
    confirmations: dict[str, Any],
    items: list[ReviewItem],
) -> tuple[float, float, float | None, str]:
    meta_levels = layout["meta"].get("levels") or {}
    if {"floor_z", "ceiling_z", "slab_to_slab"} <= set(meta_levels):
        floor_z = float(meta_levels["floor_z"])
        ceiling_z = float(meta_levels["ceiling_z"])
        slab = float(meta_levels["slab_to_slab"])
        if not (floor_z < ceiling_z <= floor_z + slab):
            items.append(
                ReviewItem(
                    "levels_inconsistent",
                    "blocking",
                    [],
                    f"meta.levels violates floor_z < ceiling_z <= floor_z + slab_to_slab "
                    f"({floor_z}, {ceiling_z}, {slab})",
                )
            )
            return floor_z, ceiling_z, None, "meta"
        return floor_z, ceiling_z, slab, "meta"
    if {"floor_z", "ceiling_z"} <= set(meta_levels):
        # Lane B: measured floor/ceiling without slab_to_slab -> the card supplies the slab
        floor_z = float(meta_levels["floor_z"])
        ceiling_z = float(meta_levels["ceiling_z"])
    else:
        floor_z = 0.0
        heights = Counter(float(w["height"]) for w in commit0_layout.get("walls", []))
        ceiling_z = heights.most_common(1)[0][0] if heights else 2700.0
    confirmed = confirmations.get("slab_to_slab_mm")
    if confirmed is None:
        items.append(
            ReviewItem(
                "levels_missing",
                "blocking",
                [],
                "meta.levels absent: confirm slab_to_slab_mm on the review card",
            )
        )
        return floor_z, ceiling_z, None, "missing"
    slab = float(confirmed)
    if not (SLAB_TO_SLAB_MIN_MM <= slab <= SLAB_TO_SLAB_MAX_MM) or slab <= ceiling_z - floor_z:
        items.append(
            ReviewItem(
                "levels_inconsistent",
                "blocking",
                [],
                f"confirmed slab_to_slab_mm {slab} must lie in "
                f"[{SLAB_TO_SLAB_MIN_MM:.0f}, {SLAB_TO_SLAB_MAX_MM:.0f}] and exceed the "
                f"{ceiling_z - floor_z:.0f} mm ceiling height",
            )
        )
        return floor_z, ceiling_z, None, "confirmation"
    return floor_z, ceiling_z, slab, "confirmation"


def _resolve_panel(
    layout: dict[str, Any],
    walls: dict[str, dict[str, Any]],
    confirmations: dict[str, Any],
    items: list[ReviewItem],
) -> tuple[tuple[float, float] | None, str, tuple[float, float] | None, str | None]:
    panel: tuple[float, float] | None = None
    source = "missing"
    meta_panel = (layout["meta"].get("electrical") or {}).get("panel")
    if meta_panel is not None:
        panel, source = (float(meta_panel[0]), float(meta_panel[1])), "meta"
    else:
        risers = sorted(
            (r for r in layout.get("risers", []) if r["type"] == "electrical"),
            key=lambda r: r["id"],
        )
        if risers:
            panel = (float(risers[0]["center"][0]), float(risers[0]["center"][1]))
            source = f"riser:{risers[0]['id']}"
        elif confirmations.get("panel") is not None:
            p = confirmations["panel"]
            panel, source = (float(p[0]), float(p[1])), "confirmation"
    if panel is None:
        items.append(
            ReviewItem(
                "panel_missing",
                "blocking",
                [],
                "no meta.electrical.panel, no electrical riser: confirm the panel location "
                "on the review card (E-4 home runs are not routed until then)",
            )
        )
        return None, source, None, None
    best: tuple[float, str] | None = None
    for wall_id in sorted(walls):
        dist = wall_line(walls[wall_id]).distance(Point(panel))
        if best is None or dist < best[0]:
            best = (dist, wall_id)
    if best is None or best[0] > PANEL_MAX_WALL_DIST_MM:
        raise MepError(
            "panel_not_on_wall",
            f"panel {panel} is farther than {PANEL_MAX_WALL_DIST_MM:.0f} mm from every wall",
        )
    wall = walls[best[1]]
    foot = pt_on_wall(wall, max(0.0, min(wall_len(wall), offset_of(panel, wall))))
    return panel, source, (round(foot[0], 1), round(foot[1], 1)), best[1]


def _counter_walls(
    layout: dict[str, Any],
    walls: dict[str, dict[str, Any]],
    rooms: dict[str, dict[str, Any]],
    polygons: dict[str, Polygon],
    host_walls: dict[str, str],
    items: list[ReviewItem],
) -> tuple[dict[str, list[str]], str, dict[tuple[str, str], list[tuple[float, float]]]]:
    """PIN-18: casework is_counter runs (spec); when the layout has NO casework at
    all, kitchen sink/dishwasher host walls define a derived counter run."""
    runs: dict[tuple[str, str], list[tuple[float, float]]] = {}
    casework = layout.get("casework") or []
    if casework:
        for run in sorted(casework, key=lambda c: c["id"]):
            if not run.get("is_counter"):
                continue
            wall = walls.get(run["host_wall_id"])
            if wall is None:
                continue
            t0, t1 = float(run["offset"]), float(run["offset"] + run["length"])
            mid = pt_on_wall(wall, (t0 + t1) / 2)
            nx, ny = left_normal(wall)
            candidates = [
                rid
                for rid in sorted(rooms)
                if run["host_wall_id"] in rooms[rid]["boundary_wall_ids"]
                and (
                    polygons[rid].covers(Point(mid[0] + nx, mid[1] + ny))
                    or polygons[rid].covers(Point(mid[0] - nx, mid[1] - ny))
                )
            ]
            kitchens = [rid for rid in candidates if rooms[rid]["program"] == "kitchen"]
            room_id = (kitchens or candidates or [None])[0]
            if room_id is None:
                continue
            runs.setdefault((room_id, run["host_wall_id"]), []).append((t0, t1))
        source = "casework"
    else:
        for room_id, item in placed_items(layout):
            room = rooms[room_id]
            if room["program"] != "kitchen" or item["kind"] not in COUNTER_FIXTURE_KINDS:
                continue
            wall_id = host_walls[item["id"]]
            t0, t1 = _extent_along(item, walls[wall_id])
            runs.setdefault((room_id, wall_id), []).append(
                (t0 - E2_COUNTER_FALLBACK_EXTEND_MM, t1 + E2_COUNTER_FALLBACK_EXTEND_MM)
            )
        # fixed appliances on the same wall break the counter (a GFCI behind a range
        # is unreachable)
        for room_id, item in placed_items(layout):
            if item["kind"] not in COUNTER_APPLIANCE_KINDS:
                continue
            key = (room_id, host_walls[item["id"]])
            if key in runs:
                cut = _extent_along(item, walls[key[1]])
                runs[key] = _subtract(runs[key], [cut])
        source = "derived" if runs else "none"
        if runs:
            items.append(
                ReviewItem(
                    "counter_walls_derived",
                    "info",
                    sorted({w for _r, w in runs}),
                    "layout has no casework: counter walls derived from the kitchen sink/"
                    "dishwasher host walls (+/-600 mm), appliances subtracted",
                )
            )
    counter_walls: dict[str, list[str]] = {}
    for (room_id, wall_id), intervals in runs.items():
        wall = walls[wall_id]
        clamped = _merge(
            [(max(0.0, a), min(wall_len(wall), b)) for a, b in intervals if b - a > 1.0]
        )
        if clamped:
            runs[(room_id, wall_id)] = clamped
            counter_walls.setdefault(room_id, []).append(wall_id)
    for room_id in counter_walls:
        counter_walls[room_id].sort()
    return counter_walls, source, {k: v for k, v in runs.items() if v}


def _extent_along(item: dict[str, Any], wall: dict[str, Any]) -> tuple[float, float]:
    offsets = [offset_of((x, y), wall) for x, y in furniture_rect(item).exterior.coords[:4]]
    return (min(offsets), max(offsets))


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _subtract(
    intervals: list[tuple[float, float]], cuts: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    out = list(intervals)
    for c0, c1 in cuts:
        nxt: list[tuple[float, float]] = []
        for a, b in out:
            if c1 <= a or c0 >= b:
                nxt.append((a, b))
                continue
            if a < c0:
                nxt.append((a, c0))
            if c1 < b:
                nxt.append((c1, b))
        out = nxt
    return [(a, b) for a, b in out if b - a > 1.0]


def resolve_inputs(
    furnished_layout: dict[str, Any],
    commit0_layout: dict[str, Any],
    confirmations: dict[str, Any] | None = None,
    placer_wall_ids: dict[str, str] | None = None,
    deadline_check: DeadlineCheck = None,
) -> MepInputs:
    confirmations = confirmations or {}
    placer_wall_ids = placer_wall_ids or {}
    layout = copy.deepcopy(furnished_layout)
    items: list[ReviewItem] = []
    walls = {w["id"]: w for w in layout["walls"]}
    rooms = {r["id"]: r for r in layout["rooms"]}
    polygons = {r["id"]: Polygon(r["boundary"]) for r in layout["rooms"]}

    floor_z, ceiling_z, slab, levels_source = _resolve_levels(
        layout, commit0_layout, confirmations, items
    )
    if slab is not None:
        layout["meta"]["levels"] = {
            "floor_z": floor_z,
            "ceiling_z": ceiling_z,
            "slab_to_slab": slab,
        }
    h_plenum = slab - (ceiling_z - floor_z) if slab is not None else None
    if deadline_check:
        deadline_check()

    panel, panel_source, panel_node, panel_wall_id = _resolve_panel(
        layout, walls, confirmations, items
    )
    if panel is not None:
        layout["meta"].setdefault("electrical", {})["panel"] = [panel[0], panel[1]]

    outlet_spacing = float(
        layout.get("constraints", {}).get("outlet_spacing") or E1_DEFAULT_SPACING_MM
    )
    if outlet_spacing < E1_MIN_OUTLET_SPACING_MM:
        items.append(
            ReviewItem(
                "outlet_spacing_invalid",
                "blocking",
                [],
                f"constraints.outlet_spacing {outlet_spacing:.0f} mm is below the "
                f"{E1_MIN_OUTLET_SPACING_MM:.0f} mm minimum run",
            )
        )

    host_walls: dict[str, str] = {}
    for room_id, item in placed_items(layout):
        host_walls[item["id"]] = _resolve_host_wall(
            item, rooms[room_id], walls, placer_wall_ids.get(item["id"])
        )

    table = plumbing_table()
    h_fitting = float(table["default_fitting_allowance_mm"])
    fixtures: list[Fixture] = []
    sanitary_rooms: set[str] = set()
    for room_id, item in placed_items(layout):
        if "sanitary" not in (item.get("hookups") or []):
            continue
        sanitary_rooms.add(room_id)
        spec = table["fixtures"].get(item["kind"])
        if spec is None:
            items.append(
                ReviewItem(
                    "fixture_kind_unknown",
                    "blocking",
                    [item["id"]],
                    f"kind {item['kind']!r} has no entry in catalogs/plumbing.json",
                )
            )
            continue
        drain = float(spec["drain_diameter_mm"])
        fixtures.append(
            Fixture(
                item=item,
                room_id=room_id,
                host_wall_id=host_walls[item["id"]],
                kind=item["kind"],
                fixture_units=float(item.get("fixture_units") or spec["fixture_units"]),
                drain_mm=drain,
                slope=drain_slope(drain),
            )
        )
    fixtures.sort(key=lambda f: f.id)
    if h_plenum is not None:
        shallow = [f.id for f in fixtures if h_plenum - f.drain_mm - h_fitting <= 0]
        if shallow:
            items.append(
                ReviewItem(
                    "plenum_too_shallow",
                    "blocking",
                    shallow,
                    f"h_plenum {h_plenum:.0f} mm leaves no slope budget for these drains",
                )
            )

    declared = {r["id"] for r in layout["rooms"] if r.get("wet_zone")}
    derived = sorted(sanitary_rooms - declared)
    wet_rooms = sorted(declared | sanitary_rooms)

    counter_walls, counter_source, counter_runs = _counter_walls(
        layout, walls, rooms, polygons, host_walls, items
    )
    return MepInputs(
        layout=layout,
        walls=walls,
        rooms=rooms,
        polygons=polygons,
        floor_z=floor_z,
        ceiling_z=ceiling_z,
        slab_to_slab=slab,
        h_plenum=h_plenum,
        h_fitting=h_fitting,
        levels_source=levels_source,
        panel=panel,
        panel_source=panel_source,
        panel_node=panel_node,
        panel_wall_id=panel_wall_id,
        outlet_spacing=outlet_spacing,
        wet_rooms=wet_rooms,
        derived_wet_rooms=derived,
        counter_walls=counter_walls,
        counter_source=counter_source,
        counter_runs=counter_runs,
        fixtures=fixtures,
        host_walls=host_walls,
        items=items,
    )


def si8_flagged(wall: dict[str, Any]) -> bool:
    return any(wall.get(flag) for flag in SI8_FLAGS)


def point_distance_to_wall(point: tuple[float, float], wall: dict[str, Any]) -> float:
    return float(wall_line(wall).distance(Point(point)))


def wall_distance_to_point(wall: dict[str, Any], point: tuple[float, float]) -> float:
    return point_distance_to_wall(point, wall)


def deg(v: float) -> float:
    return math.degrees(v)
