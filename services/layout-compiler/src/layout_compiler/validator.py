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
from functools import cache
from typing import Any

import jsonschema
from chapter_contracts.generated.chapter_layout import ChapterLayout
from shapely.geometry import LineString, Point, Polygon

from layout_compiler.catalogs import (
    CONTRACTS_DIR,
    asbuilt_wall_types,
    door_types,
    family_types,
    new_families,
    new_wall_types,
    window_types,
)
from layout_compiler.geometry import (
    BOUNDARY_EDGE_TOLERANCE_MM,
    OVERLAP_EPS_MM2,
    circulation_errors,
    furniture_rect,
    room_free_space,
    room_thresholds,
    wall_len,
    wall_thickness_of,
)
from layout_compiler.swing import room_swing_arcs

DEFAULT_CIRCULATION_MIN_MM = 915.0  # packages/contracts/README.md defaults table
EDGE_SAMPLE_STEP_MM = 100.0  # boundary edges sampled per-point: collinear walls may share one edge

# Room min clear widths (inscribed-width check): engineering defaults, human-reviewable,
# same status as the plumbing defaults table. Corridor = max(900, circulation_min), inline.
MIN_WIDTH_MM: dict[str, float] = {
    "bedroom": 2000.0,
    "living": 2000.0,
    "dining": 2000.0,
    "office": 2000.0,
    "kitchen": 1800.0,
    "bathroom": 900.0,
    "powder": 900.0,
    "laundry": 900.0,
    "closet": 900.0,
    "other": 900.0,
}


def _layout_schema() -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / "schemas" / "chapter-layout.v2.3.json").read_text())


@cache
def _op_names() -> frozenset[str]:
    registry = json.loads((CONTRACTS_DIR / "ops" / "registry.json").read_text())
    return frozenset(registry["ops"])


def validate_layout(layout: dict[str, Any], frozen: dict[str, Any] | None = None) -> list[str]:
    """`frozen` (the Commit #0 snapshot) enables the envelope check: generated
    walls must stay within the existing conditions' bounding box."""
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
    #    (furniture item ids share the namespace — they become place_family ids)
    seen_ids: set[str] = set()
    for group in ("walls", "doors", "windows", "rooms"):
        for element in layout[group]:
            if element["id"] in seen_ids:
                errors.append(f"{group}.{element['id']}: duplicate element id")
            seen_ids.add(element["id"])
    for entry in layout["furniture"]:
        for item in entry["items"]:
            if item["id"] in seen_ids:
                errors.append(f"furniture.{item['id']}: duplicate element id")
            seen_ids.add(item["id"])
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
                    f"walls.{wall['id']}: revit_type {wall['revit_type']!r} not in "
                    "asbuilt_types.json"
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
    # furniture vocabulary is closed too (Phase 5): family + type from the
    # catalog, kind consistent, footprint EXACTLY the catalog's — the LLM
    # proposes what goes where, never geometry
    for entry in layout["furniture"]:
        for item in entry["items"]:
            if item["revit_family"] not in new_families():
                errors.append(
                    f"furniture.{item['id']}: revit_family {item['revit_family']!r} not in "
                    "new_construction_types.json families (closed vocabulary)"
                )
                continue
            spec = family_types().get((item["revit_family"], item["revit_type"]))
            if spec is None:
                errors.append(
                    f"furniture.{item['id']}: revit_type {item['revit_type']!r} is not a "
                    f"catalog type of {item['revit_family']!r}"
                )
                continue
            if item["kind"] not in spec["kinds"]:
                errors.append(
                    f"furniture.{item['id']}: kind {item['kind']!r} not offered by "
                    f"{item['revit_family']!r}"
                )
            if [float(v) for v in item["footprint"]] != spec["footprint_mm"]:
                errors.append(
                    f"furniture.{item['id']}: footprint must match the catalog "
                    f"{spec['footprint_mm']} for {item['revit_type']!r}"
                )

    # generated walls must bound at least one room (a wall bounding nothing is
    # floating or outside the plan — also the cheap envelope-closure rule)
    bounded = {wall_id for r in layout["rooms"] for wall_id in r["boundary_wall_ids"]}
    for wall in layout["walls"]:
        if wall.get("source") == "generated" and wall["id"] not in bounded:
            errors.append(
                f"walls.{wall['id']}: generated wall bounds no room (floating or outside "
                "the envelope)"
            )

    # SI-7 output guard: op-registry vocabulary laundered into free text is
    # rejected (repairable — it is content, not identity)
    free_text = [("rooms", r["id"], r["name"]) for r in layout["rooms"]]
    free_text += [
        ("constraints", "style_tags", tag)
        for tag in layout.get("constraints", {}).get("style_tags", [])
    ]
    for group, ident, text in free_text:
        lowered = text.lower()
        if any(op_name in lowered for op_name in _op_names()):
            errors.append(f"{group}.{ident}: free text contains op-registry vocabulary (SI-7)")

    if errors:
        return sorted(errors)  # geometry needs sane references; report and stop

    # 4a. openings within their host span (same predicate the sim enforces) and
    #     with a clear span no other wall abuts into
    for group in ("doors", "windows"):
        for opening in layout[group]:
            host = walls[opening["host_wall_id"]]
            length = wall_len(host)
            lo = opening["offset"] - opening["width"] / 2
            hi = opening["offset"] + opening["width"] / 2
            if lo < 0 or hi > length:
                errors.append(
                    f"{group}.{opening['id']}: offset {opening['offset']} ± width/2 outside host "
                    f"{host['id']} (length {length:.0f})"
                )
                continue
            host_line = LineString([host["start"], host["end"]])
            host_t = wall_thickness_of(host) or 0.0
            for other in layout["walls"]:
                if other["id"] == host["id"]:
                    continue
                for pt in (other["start"], other["end"]):
                    point = Point(pt)
                    if (
                        host_line.distance(point) <= host_t / 2 + BOUNDARY_EDGE_TOLERANCE_MM
                        and lo + 1.0 < host_line.project(point) < hi - 1.0
                    ):
                        errors.append(
                            f"{group}.{opening['id']}: wall {other['id']} abuts host "
                            f"{host['id']} inside the opening clear span"
                        )
                        break

    # 4a'. envelope: generated walls stay within the existing conditions' AABB
    if frozen is not None:
        points = [pt for w in frozen["walls"] for pt in (w["start"], w["end"])]
        min_x = min(p[0] for p in points) - BOUNDARY_EDGE_TOLERANCE_MM
        max_x = max(p[0] for p in points) + BOUNDARY_EDGE_TOLERANCE_MM
        min_y = min(p[1] for p in points) - BOUNDARY_EDGE_TOLERANCE_MM
        max_y = max(p[1] for p in points) + BOUNDARY_EDGE_TOLERANCE_MM
        for wall in layout["walls"]:
            if wall.get("source") != "generated":
                continue
            for pt in (wall["start"], wall["end"]):
                if not (min_x <= pt[0] <= max_x and min_y <= pt[1] <= max_y):
                    errors.append(
                        f"walls.{wall['id']}: endpoint ({pt[0]:.0f},{pt[1]:.0f}) outside the "
                        "existing envelope"
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

        # every boundary edge lies within t/2 (+1mm) of the boundary wall centerlines,
        # sampled every 100mm so collinear walls may share one edge (architect pass);
        # every listed wall must in turn cover at least one sample (no phantom listings)
        centerlines: list[tuple[str, LineString, float]] = []
        for wall_id in room["boundary_wall_ids"]:
            wall = walls[wall_id]
            thickness = wall_thickness_of(wall)
            if thickness is None:
                errors.append(f"rooms.{room['id']}: wall {wall_id} has no resolvable thickness")
                continue
            centerlines.append((wall_id, LineString([wall["start"], wall["end"]]), thickness))
        ring = [*boundary, boundary[0]]
        matched_walls: set[str] = set()
        for a, b in zip(ring, ring[1:], strict=False):
            edge = LineString([a, b])
            steps = max(1, math.ceil(edge.length / EDGE_SAMPLE_STEP_MM))
            uncovered = False
            for i in range(steps + 1):
                sample = edge.interpolate(i / steps, normalized=True)
                covering = [
                    wall_id
                    for wall_id, line, t in centerlines
                    if line.distance(sample) <= t / 2 + BOUNDARY_EDGE_TOLERANCE_MM
                ]
                if covering:
                    matched_walls.update(covering)
                else:
                    uncovered = True
            if uncovered:
                errors.append(
                    f"rooms.{room['id']}: boundary edge {a}->{b} lies on no boundary wall "
                    "centerline (within half thickness)"
                )
        for wall_id, _line, _t in centerlines:
            if wall_id not in matched_walls:
                errors.append(
                    f"rooms.{room['id']}: listed boundary wall {wall_id} touches no boundary edge"
                )

        # per-program min clear width (inscribed-width erosion, architect pass)
        program = room["program"]
        min_width = (
            max(900.0, circulation_min)
            if program == "corridor"
            else MIN_WIDTH_MM.get(program, 900.0)
        )
        if polygon.buffer(-min_width / 2).is_empty:
            errors.append(
                f"rooms.{room['id']}: {program} min clear width {min_width:.0f}mm not met"
            )

        # Phase 5 furniture geometry: every footprint inside the room (centerline
        # bound, `covers` so boundary-touching is legal) and pairwise POSITIVE-AREA
        # disjoint (touching is legal — a flush kitchen run shares edges)
        room_items = [
            item
            for entry in layout["furniture"]
            if entry["room_id"] == room["id"]
            for item in entry["items"]
        ]
        rects = [(item["id"], furniture_rect(item)) for item in room_items]
        room_cover = polygon.buffer(0.01)
        for item_id, rect in rects:
            if not room_cover.covers(rect):
                errors.append(
                    f"rooms.{room['id']}: furniture {item_id} footprint outside the room boundary"
                )
        for i, (id_a, rect_a) in enumerate(rects):
            for id_b, rect_b in rects[i + 1 :]:
                overlap = rect_a.intersection(rect_b).area
                if overlap > OVERLAP_EPS_MM2:
                    errors.append(
                        f"furniture.{id_a}~{id_b}: footprints overlap ({overlap:.0f} mm²)"
                    )
        if rects:
            for door_id, arc in room_swing_arcs(room, polygon, layout["doors"], walls):
                for item_id, rect in rects:
                    swept = rect.intersection(arc).area
                    if swept > OVERLAP_EPS_MM2:
                        errors.append(
                            f"rooms.{room['id']}: furniture {item_id} intersects door "
                            f"{door_id} swing arc ({swept:.0f} mm²)"
                        )

        # free space = room minus furniture footprints (inflated by clearances),
        # then the Part G circulation check — both shared with the interior
        # placer via geometry.py (one implementation, validator-stable strings)
        free = room_free_space(polygon, room_items)
        thresholds = room_thresholds(room, polygon, layout["doors"], walls)
        errors.extend(circulation_errors(room["id"], free, thresholds, circulation_min))

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
