"""Shared placement geometry (Part G): the primitives the validator and the
Phase 5 interior placer must agree on, extracted verbatim from the validator so
there is exactly ONE implementation of each predicate. Error strings produced
here are part of the validator's stable output (the repair loop feeds them to
the LLM verbatim) — never reword them casually.

shapely is used for polygon predicates only: verdicts, never golden bytes."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from layout_compiler.catalogs import wall_thickness_mm

BOUNDARY_EDGE_TOLERANCE_MM = 1.0  # edge-to-centerline slack on top of t/2
# Overlap = POSITIVE-AREA intersection; touching footprints are legal (a flush
# kitchen run shares edges, and the sim's interference check is strict-<).
OVERLAP_EPS_MM2 = 1e-3


def pt_on_wall(wall: dict[str, Any], offset: float) -> tuple[float, float]:
    """Centerline placement convention (Part D): start + offset * unit(end-start)."""
    sx, sy = wall["start"]
    ex, ey = wall["end"]
    length = math.hypot(ex - sx, ey - sy)
    if length == 0:
        return (sx, sy)
    return (sx + (ex - sx) * offset / length, sy + (ey - sy) * offset / length)


def wall_len(wall: dict[str, Any]) -> float:
    return math.hypot(wall["end"][0] - wall["start"][0], wall["end"][1] - wall["start"][1])


def wall_thickness_of(wall: dict[str, Any]) -> float | None:
    if wall.get("as_built_thickness"):
        return float(wall["as_built_thickness"])
    return wall_thickness_mm().get(wall["revit_type"])


def furniture_rect(item: dict[str, Any]) -> Polygon:
    """The item's oriented footprint rectangle: centered rect -> rotate CCW about
    the origin -> translate to center (D1 footprint semantics, same as the sim)."""
    cx, cy = item["center"]
    w, d = item["footprint"]
    rect = Polygon([(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)])
    rect = affinity.rotate(rect, item["rotation_deg"], origin=(0, 0))
    return affinity.translate(rect, cx, cy)


def clearance_blob(item: dict[str, Any]) -> Polygon:
    """Footprint inflated by the item's clearance (round corners — the validator's
    exact semantics; clearance_front absent means 0)."""
    return furniture_rect(item).buffer(float(item.get("clearance_front", 0)))


def room_free_space(polygon: Polygon, items: Iterable[dict[str, Any]]) -> BaseGeometry:
    """Room boundary polygon minus every item's inflated footprint (Part G)."""
    free: BaseGeometry = polygon
    for item in items:
        free = free.difference(clearance_blob(item))
    return free


def room_thresholds(
    room: dict[str, Any],
    polygon: Polygon,
    doors: list[dict[str, Any]],
    walls_by_id: dict[str, dict[str, Any]],
) -> list[tuple[str, tuple[float, float]]]:
    """A room's circulation thresholds: the doors ON ITS OWN boundary. A shared
    wall (e.g. a full-height spine) hosts doors for several rooms, and a door
    beyond this room's edge extent is another room's door."""
    thresholds: list[tuple[str, tuple[float, float]]] = []
    for door in doors:
        if door["host_wall_id"] not in room["boundary_wall_ids"]:
            continue
        pt = pt_on_wall(walls_by_id[door["host_wall_id"]], door["offset"])
        if polygon.exterior.distance(Point(pt)) <= BOUNDARY_EDGE_TOLERANCE_MM:
            thresholds.append((door["id"], pt))
    return thresholds


def circulation_errors(
    room_id: str,
    free: BaseGeometry,
    thresholds: list[tuple[str, tuple[float, float]]],
    circulation_min: float,
) -> list[str]:
    """Part G circulation, operational definition: erode the free space by
    circulation_min/2; every threshold must be reachable and all thresholds must
    fall in ONE connected component. Error strings are validator-stable."""
    errors: list[str] = []
    eroded = free.buffer(-circulation_min / 2)
    if thresholds and eroded.is_empty:
        errors.append(
            f"rooms.{room_id}: free space vanishes under circulation erosion "
            f"({circulation_min:.0f}mm) — min width violated"
        )
        return errors
    if len(thresholds) >= 1 and not eroded.is_empty:
        parts = list(eroded.geoms) if hasattr(eroded, "geoms") else [eroded]
        components = []
        for _door_id, (tx, ty) in thresholds:
            point = Point(tx, ty)
            best = min(range(len(parts)), key=lambda i: parts[i].distance(point))
            if parts[best].distance(point) > circulation_min:
                errors.append(
                    f"rooms.{room_id}: door threshold ({tx:.0f},{ty:.0f}) unreachable "
                    "from the room's circulation space"
                )
            components.append(best)
        if len(set(components)) > 1:
            errors.append(
                f"rooms.{room_id}: door thresholds fall in disconnected circulation "
                f"components (circulation_min {circulation_min:.0f}mm)"
            )
    return errors


def edge_probe_line(wall: dict[str, Any]) -> LineString:
    return LineString([wall["start"], wall["end"]])
