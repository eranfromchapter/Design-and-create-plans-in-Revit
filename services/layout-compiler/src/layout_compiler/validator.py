"""Deterministic layout validator (PLAN.md Part E Phase 4 + Part G room geometry).

Order: contract schema -> referential integrity -> catalog membership ->
geometry (room polygons simple + consistent with wall centerlines, doors within
host span, min free width, circulation connectivity). Returns a STABLE sorted
list of error strings (empty = valid) — the repair loop feeds these back to the
LLM verbatim, and hypothesis asserts the verdict function is total.

shapely is used for polygon predicates only: the validator emits verdicts, never
golden bytes, so float determinism is not load-bearing here (unlike the
scan-converter's geometry, which lands in byte-compared SVGs).

Immutability of existing elements is NOT this module's job — the architectural
diff (Part G identity spec) rejects any moved/renumbered source="scan" element
against the frozen Commit #0 snapshot."""

from __future__ import annotations

import json
import math
from typing import Any

import jsonschema
from chapter_contracts.generated.chapter_layout import ChapterLayout
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon

from layout_compiler.catalogs import (
    CONTRACTS_DIR,
    asbuilt_wall_types,
    door_types,
    new_wall_types,
    wall_thickness_mm,
    window_types,
)

DEFAULT_CIRCULATION_MIN_MM = 915.0  # packages/contracts/README.md defaults table
BOUNDARY_EDGE_TOLERANCE_MM = 1.0  # edge-to-centerline slack on top of t/2


def _layout_schema() -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / "schemas" / "chapter-layout.v2.3.json").read_text())


def _pt_on_wall(wall: dict[str, Any], offset: float) -> tuple[float, float]:
    """Centerline placement convention (Part D): start + offset * unit(end-start)."""
    sx, sy = wall["start"]
    ex, ey = wall["end"]
    length = math.hypot(ex - sx, ey - sy)
    if length == 0:
        return (sx, sy)
    return (sx + (ex - sx) * offset / length, sy + (ey - sy) * offset / length)


def _wall_len(wall: dict[str, Any]) -> float:
    return math.hypot(wall["end"][0] - wall["start"][0], wall["end"][1] - wall["start"][1])


def _thickness(wall: dict[str, Any]) -> float | None:
    if wall.get("as_built_thickness"):
        return float(wall["as_built_thickness"])
    return wall_thickness_mm().get(wall["revit_type"])


def validate_layout(layout: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    # 1. contract schema (strict pydantic + raw JSON schema)
    try:
        ChapterLayout.model_validate(layout)
        jsonschema.validate(layout, _layout_schema(), format_checker=jsonschema.FormatChecker())
    except Exception as err:
        first_line = str(err).splitlines()[0][:300]
        return [f"schema: {first_line}"]  # nothing below is meaningful on a malformed doc

    if layout["meta"]["phase"] != "new":
        errors.append('meta.phase: compiler output must be "new"')
    if not layout["rooms"]:
        errors.append("rooms: a compiled layout must define at least one room")

    walls = {w["id"]: w for w in layout["walls"]}
    rooms = {r["id"]: r for r in layout["rooms"]}

    # 2. referential integrity + id uniqueness across element classes
    seen_ids: set[str] = set()
    for group in ("walls", "doors", "windows", "rooms"):
        for element in layout[group]:
            if element["id"] in seen_ids:
                errors.append(f"{group}.{element['id']}: duplicate element id")
            seen_ids.add(element["id"])
    for group in ("doors", "windows"):
        for opening in layout[group]:
            if opening["host_wall_id"] not in walls:
                errors.append(
                    f"{group}.{opening['id']}: unknown host wall {opening['host_wall_id']}"
                )
    for room in layout["rooms"]:
        for wall_id in room["boundary_wall_ids"]:
            if wall_id not in walls:
                errors.append(f"rooms.{room['id']}: unknown boundary wall {wall_id}")
        for adjacent in room.get("adjacent_room_ids", []):
            if adjacent not in rooms:
                errors.append(f"rooms.{room['id']}: unknown adjacent room {adjacent}")
    for entry in layout["furniture"]:
        if entry["room_id"] not in rooms:
            errors.append(f"furniture.{entry['room_id']}: unknown room")

    # 3. catalog membership (D1): every wall declares its provenance; generated
    #    vocabulary is closed, scan walls resolve via the as-built catalog
    for wall in layout["walls"]:
        source = wall.get("source")
        if source == "generated":
            if wall["revit_type"] not in new_wall_types():
                errors.append(
                    f"walls.{wall['id']}: revit_type {wall['revit_type']!r} not in "
                    "new_construction_types.json (closed vocabulary)"
                )
        elif source == "scan":
            if wall["revit_type"] not in asbuilt_wall_types():
                errors.append(
                    f"walls.{wall['id']}: revit_type {wall['revit_type']!r} not in asbuilt_types.json"
                )
        else:
            errors.append(f"walls.{wall['id']}: compiler output must set source scan|generated")
    for door in layout["doors"]:
        if door["revit_type"] not in door_types():
            errors.append(
                f"doors.{door['id']}: revit_type {door['revit_type']!r} not in any catalog"
            )
    for window in layout["windows"]:
        if window["revit_type"] not in window_types():
            errors.append(
                f"windows.{window['id']}: revit_type {window['revit_type']!r} not in any catalog"
            )

    if errors:
        return sorted(errors)  # geometry needs sane references; report and stop

    # 4a. openings within their host span (same predicate the sim enforces)
    for group in ("doors", "windows"):
        for opening in layout[group]:
            host = walls[opening["host_wall_id"]]
            length = _wall_len(host)
            if opening["offset"] - opening["width"] / 2 < 0 or (
                opening["offset"] + opening["width"] / 2 > length
            ):
                errors.append(
                    f"{group}.{opening['id']}: offset {opening['offset']} ± width/2 outside host "
                    f"{host['id']} (length {length:.0f})"
                )

    circulation_min = float(
        layout.get("constraints", {}).get("circulation_min", DEFAULT_CIRCULATION_MIN_MM)
    )

    # 4b. per-room geometry
    for room in layout["rooms"]:
        boundary = room["boundary"]
        if boundary[0] == boundary[-1]:
            errors.append(
                f"rooms.{room['id']}: boundary repeats the first vertex (implicit closure)"
            )
            continue
        polygon = Polygon(boundary)
        if not polygon.is_valid or not polygon.is_simple or polygon.area <= 0:
            errors.append(f"rooms.{room['id']}: boundary is not a simple positive-area polygon")
            continue

        # every boundary edge lies within t/2 (+1mm) of some boundary wall centerline
        centerlines: list[tuple[str, LineString, float]] = []
        for wall_id in room["boundary_wall_ids"]:
            wall = walls[wall_id]
            thickness = _thickness(wall)
            if thickness is None:
                errors.append(f"rooms.{room['id']}: wall {wall_id} has no resolvable thickness")
                continue
            centerlines.append((wall_id, LineString([wall["start"], wall["end"]]), thickness))
        ring = [*boundary, boundary[0]]
        for a, b in zip(ring, ring[1:], strict=False):
            edge = LineString([a, b])
            probes = [Point(a), Point(b), edge.interpolate(0.5, normalized=True)]
            if not any(
                all(line.distance(p) <= t / 2 + BOUNDARY_EDGE_TOLERANCE_MM for p in probes)
                for _, line, t in centerlines
            ):
                errors.append(
                    f"rooms.{room['id']}: boundary edge {a}->{b} lies on no boundary wall "
                    "centerline (within half thickness)"
                )

        # free space = room minus furniture footprints (inflated by clearances)
        free = polygon
        for entry in layout["furniture"]:
            if entry["room_id"] != room["id"]:
                continue
            for item in entry["items"]:
                cx, cy = item["center"]
                w, d = item["footprint"]
                rect = Polygon([(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)])
                rect = affinity.rotate(rect, item["rotation_deg"], origin=(0, 0))
                rect = affinity.translate(rect, cx, cy)
                clearance = float(item.get("clearance_front", 0))
                free = free.difference(rect.buffer(clearance))

        eroded = free.buffer(-circulation_min / 2)
        thresholds = [
            _pt_on_wall(walls[door["host_wall_id"]], door["offset"])
            for door in layout["doors"]
            if door["host_wall_id"] in room["boundary_wall_ids"]
        ]
        if thresholds and eroded.is_empty:
            errors.append(
                f"rooms.{room['id']}: free space vanishes under circulation erosion "
                f"({circulation_min:.0f}mm) — min width violated"
            )
            continue
        if len(thresholds) >= 1 and not eroded.is_empty:
            parts = list(eroded.geoms) if hasattr(eroded, "geoms") else [eroded]
            components = []
            for tx, ty in thresholds:
                point = Point(tx, ty)
                best = min(range(len(parts)), key=lambda i: parts[i].distance(point))
                if parts[best].distance(point) > circulation_min:
                    errors.append(
                        f"rooms.{room['id']}: door threshold ({tx:.0f},{ty:.0f}) unreachable "
                        "from the room's circulation space"
                    )
                components.append(best)
            if len(set(components)) > 1:
                errors.append(
                    f"rooms.{room['id']}: door thresholds fall in disconnected circulation "
                    f"components (circulation_min {circulation_min:.0f}mm)"
                )

    # 4c. rooms must not overlap each other (interiors disjoint; shared edges fine)
    room_list = layout["rooms"]
    for i, ra in enumerate(room_list):
        pa = Polygon(ra["boundary"])
        for rb in room_list[i + 1 :]:
            pb = Polygon(rb["boundary"])
            if pa.is_valid and pb.is_valid:
                overlap = pa.intersection(pb).area
                if overlap > 1e4:  # > 100 cm² — beyond shared-wall slack
                    errors.append(
                        f"rooms.{ra['id']}~{rb['id']}: boundaries overlap ({overlap:.0f} mm²)"
                    )

    return sorted(errors)
