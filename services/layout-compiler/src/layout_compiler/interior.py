"""Deterministic Part G interior placer (Phase 5). No LLM, no RNG, no clock:
the same proposals against the same layout produce byte-identical output.

Greedy wall-seeking (Part G, exactly): items sorted by footprint area desc;
walls nearest the proposed center first; per wall, tangential slides
s ∈ {0, ±50, …, ±2000} (81) × both orientations (natural, +90°) = 162
candidates/wall, slide outer / orientation inner; slides whose foot leaves the
wall segment are skipped-and-counted, never clamped. Free-standing items get a
bounded spiral around the proposed center: rings every 50mm to 500mm × 8
angles × 4 rotations = 324 candidates. Both loops are counter-asserted (SI-6).

A candidate is accepted iff (cheap first):
  (1) inside the room (centerline polygon, `covers`, boundary-touching legal)
  (2) footprint-clear vs placed same-room items, SYMMETRIC positive-area test
      (candidate blob ∩ placed rect AND candidate rect ∩ placed blob;
      blob-vs-blob overlap is legal, matching the validator's subtraction)
  (3) clear of this room's door-swing arcs (positive-area)
  (4) AABB-disjoint from EVERY placed item model-wide, the sim's exact
      interference formula with strict inequalities (touching legal) — a
      deliberate 5th predicate so Commit #2's run_interference_check can
      never fire on furniture
  (5) circulation still holds (Part G operational definition, shared
      implementation with the validator via geometry.py)
Exhausted → the item is UNPLACED (REVIEW), never force-placed."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from layout_compiler.catalogs import family_types
from layout_compiler.geometry import (
    OVERLAP_EPS_MM2,
    circulation_errors,
    clearance_blob,
    furniture_rect,
    pt_on_wall,
    room_free_space,
    room_thresholds,
    wall_len,
    wall_thickness_of,
)
from layout_compiler.swing import room_swing_arcs
from layout_compiler.validator import DEFAULT_CIRCULATION_MIN_MM

T_FINISH_MM = 0.0  # v1 pin: no finish-thickness field exists in the contract

SLIDE_SEQUENCE_MM: tuple[float, ...] = (0.0,) + tuple(
    s for step in range(1, 41) for s in (step * 50.0, -step * 50.0)
)  # 81 slides: 0, +50, -50, ..., +2000, -2000
MAX_CANDIDATES_PER_WALL = 162  # 81 slides x 2 orientations (SI-6 bound)

SPIRAL_RING_STEP_MM = 50.0
SPIRAL_MAX_OFFSET_MM = 500.0
SPIRAL_ANGLES_PER_RING = 8
SPIRAL_ROTATIONS = (0.0, 90.0, 180.0, 270.0)
SPIRAL_CAP = (1 + int(SPIRAL_MAX_OFFSET_MM / SPIRAL_RING_STEP_MM) * SPIRAL_ANGLES_PER_RING) * len(
    SPIRAL_ROTATIONS
)  # (1 + 10*8) * 4 = 324 (SI-6 bound)


def project_to_wall(
    c: tuple[float, float], wall: dict[str, Any]
) -> tuple[float, tuple[float, float]]:
    """Part G projection primitive: t* = clamp(((C-P1)·(P2-P1))/|P2-P1|², 0, 1)."""
    p1x, p1y = wall["start"]
    p2x, p2y = wall["end"]
    dx, dy = p2x - p1x, p2y - p1y
    denom = dx * dx + dy * dy
    if denom == 0:
        return 0.0, (p1x, p1y)
    t_star = max(0.0, min(1.0, ((c[0] - p1x) * dx + (c[1] - p1y) * dy) / denom))
    return t_star, (p1x + t_star * dx, p1y + t_star * dy)


def room_facing_normal(
    wall: dict[str, Any], foot: tuple[float, float], polygon: Polygon, eps: float = 1.0
) -> tuple[float, float] | None:
    """The wall normal pointing into the room at this foot (Part G: test
    F + ε·n̂ inside the boundary polygon). None when neither side is the room."""
    length = wall_len(wall)
    if length == 0:
        return None
    ux = (wall["end"][0] - wall["start"][0]) / length
    uy = (wall["end"][1] - wall["start"][1]) / length
    for nx, ny in ((-uy, ux), (uy, -ux)):
        if polygon.covers(Point(foot[0] + eps * nx, foot[1] + eps * ny)):
            return (nx, ny)
    return None


def back_to_wall_center(
    foot: tuple[float, float], n_hat: tuple[float, float], t_wall: float, d_item: float
) -> tuple[float, float]:
    """Part G: P = F + n̂·(t_wall/2 + t_finish + d_item/2)."""
    offset = t_wall / 2 + T_FINISH_MM + d_item / 2
    return (foot[0] + n_hat[0] * offset, foot[1] + n_hat[1] * offset)


def aabb_of(
    center: tuple[float, float], rotation_deg: float, footprint: tuple[float, float]
) -> tuple[float, float, float, float]:
    """The sim's exact AABB formula for a rotated oriented rectangle
    (tools/revit-sim model.py run_interference_check)."""
    cx, cy = center
    w, d = footprint
    rad = math.radians(rotation_deg)
    hx = (abs(w * math.cos(rad)) + abs(d * math.sin(rad))) / 2
    hy = (abs(w * math.sin(rad)) + abs(d * math.cos(rad))) / 2
    return (cx - hx, cy - hy, cx + hx, cy + hy)


def aabbs_overlap(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    """Strict inequalities (the sim's formula): touching AABBs do NOT overlap."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _normalize_rotation(raw: float) -> float:
    return round(raw % 360.0, 1) % 360.0


@dataclass
class ItemDiag:
    item_id: str
    room_id: str
    placed: bool = False
    method: str | None = None  # "wall" | "spiral"
    wall_id: str | None = None
    candidates_tried: int = 0
    spiral_tried: int = 0
    walls_tried: int = 0
    candidates_per_wall: dict[str, int] = field(default_factory=dict)
    reason: str | None = None


@dataclass
class FurnishOutcome:
    furniture: list[dict[str, Any]]  # layout-shaped entries [{room_id, items}]
    unplaced: list[dict[str, Any]]  # [{item, room_id, reason}]
    diagnostics: dict[str, Any]


@dataclass
class _RoomCtx:
    room: dict[str, Any]
    polygon: Polygon
    room_cover: BaseGeometry
    arcs: list[Polygon]
    thresholds: list[tuple[str, tuple[float, float]]]
    circulation_min: float
    placed: list[tuple[dict[str, Any], Polygon, BaseGeometry]]  # (item, rect, blob)


def _candidate_ok(
    candidate: dict[str, Any],
    ctx: _RoomCtx,
    base_free: BaseGeometry,
    all_aabbs: list[tuple[float, float, float, float]],
) -> bool:
    rect = furniture_rect(candidate)
    if not ctx.room_cover.covers(rect):
        return False
    blob = clearance_blob(candidate)
    for _item, placed_rect, placed_blob in ctx.placed:
        if blob.intersection(placed_rect).area > OVERLAP_EPS_MM2:
            return False
        if rect.intersection(placed_blob).area > OVERLAP_EPS_MM2:
            return False
    for arc in ctx.arcs:
        if rect.intersection(arc).area > OVERLAP_EPS_MM2:
            return False
    cand_aabb = aabb_of(
        tuple(candidate["center"]), candidate["rotation_deg"], candidate["footprint"]
    )
    for other in all_aabbs:
        if aabbs_overlap(cand_aabb, other):
            return False
    return (
        circulation_errors(
            ctx.room["id"], base_free.difference(blob), ctx.thresholds, ctx.circulation_min
        )
        == []
    )


def _anchor(proposal: dict[str, Any], polygon: Polygon) -> tuple[float, float]:
    """The proposed center, clamped to the room centroid when it lies outside."""
    cx, cy = proposal["center"]
    if polygon.covers(Point(cx, cy)):
        return (float(cx), float(cy))
    centroid = polygon.centroid
    return (centroid.x, centroid.y)


def _wall_angle_deg(wall: dict[str, Any]) -> float:
    return math.degrees(
        math.atan2(wall["end"][1] - wall["start"][1], wall["end"][0] - wall["start"][0])
    )


def _stamp(
    proposal: dict[str, Any], center: tuple[float, float], rotation_deg: float
) -> dict[str, Any]:
    item = {
        "id": proposal["id"],
        "kind": proposal["kind"],
        "revit_family": proposal["revit_family"],
        "revit_type": proposal["revit_type"],
        "center": [round(center[0], 1), round(center[1], 1)],
        "rotation_deg": _normalize_rotation(rotation_deg),
        "footprint": list(proposal["footprint"]),
        "clearance_front": proposal["clearance_front"],
        "wall_seeking": proposal["wall_seeking"],
    }
    for passthrough in ("fixture_units", "hookups"):
        if passthrough in proposal:
            item[passthrough] = proposal[passthrough]
    return item


def _place_wall_seeking(
    proposal: dict[str, Any],
    ctx: _RoomCtx,
    walls_by_id: dict[str, dict[str, Any]],
    base_free: BaseGeometry,
    all_aabbs: list[tuple[float, float, float, float]],
    diag: ItemDiag,
) -> dict[str, Any] | None:
    anchor = _anchor(proposal, ctx.polygon)
    width, depth = proposal["footprint"]
    walls = sorted(
        (walls_by_id[wid] for wid in ctx.room["boundary_wall_ids"]),
        key=lambda w: (LineString([w["start"], w["end"]]).distance(Point(anchor)), w["id"]),
    )
    for wall in walls:
        diag.walls_tried += 1
        thickness = wall_thickness_of(wall)
        if thickness is None:
            diag.candidates_per_wall[wall["id"]] = 0
            continue
        length = wall_len(wall)
        t_star, _foot = project_to_wall(anchor, wall)
        base_offset = t_star * length
        angle = _wall_angle_deg(wall)
        tried = 0
        for slide in SLIDE_SEQUENCE_MM:
            foot_offset = base_offset + slide
            for orientation in (0.0, 90.0):
                tried += 1
                assert tried <= MAX_CANDIDATES_PER_WALL  # SI-6 counter assertion
                if foot_offset < 0 or foot_offset > length:
                    continue  # skipped-and-counted, never clamped
                foot = pt_on_wall(wall, foot_offset)
                n_hat = room_facing_normal(wall, foot, ctx.polygon)
                if n_hat is None:
                    continue
                depth_from_wall = depth if orientation == 0.0 else width
                center = back_to_wall_center(foot, n_hat, thickness, depth_from_wall)
                candidate = _stamp(proposal, center, angle + orientation)
                if _candidate_ok(candidate, ctx, base_free, all_aabbs):
                    diag.candidates_per_wall[wall["id"]] = tried
                    diag.candidates_tried += tried
                    diag.placed, diag.method, diag.wall_id = True, "wall", wall["id"]
                    return candidate
        diag.candidates_per_wall[wall["id"]] = tried
        diag.candidates_tried += tried
    diag.reason = "no wall-seeking candidate satisfies the Part G predicates"
    return None


def _place_free_standing(
    proposal: dict[str, Any],
    ctx: _RoomCtx,
    base_free: BaseGeometry,
    all_aabbs: list[tuple[float, float, float, float]],
    diag: ItemDiag,
) -> dict[str, Any] | None:
    anchor = _anchor(proposal, ctx.polygon)
    positions = [anchor]
    rings = int(SPIRAL_MAX_OFFSET_MM / SPIRAL_RING_STEP_MM)
    for ring in range(1, rings + 1):
        radius = ring * SPIRAL_RING_STEP_MM
        for k in range(SPIRAL_ANGLES_PER_RING):
            theta = 2 * math.pi * k / SPIRAL_ANGLES_PER_RING
            positions.append(
                (anchor[0] + radius * math.cos(theta), anchor[1] + radius * math.sin(theta))
            )
    for position in positions:
        for rotation in SPIRAL_ROTATIONS:
            diag.spiral_tried += 1
            assert diag.spiral_tried <= SPIRAL_CAP  # SI-6 counter assertion
            candidate = _stamp(proposal, position, rotation)
            if _candidate_ok(candidate, ctx, base_free, all_aabbs):
                diag.placed, diag.method = True, "spiral"
                return candidate
    diag.reason = "no spiral candidate satisfies the Part G predicates"
    return None


def legalize_furniture(proposals: list[dict[str, Any]], layout: dict[str, Any]) -> FurnishOutcome:
    """proposals: normalized furniture proposals, each carrying room_id. Rooms
    are processed by room_id asc; items within a room by (area desc, id asc)."""
    walls_by_id = {w["id"]: w for w in layout["walls"]}
    rooms_by_id = {r["id"]: r for r in layout["rooms"]}
    circulation_min = float(
        layout.get("constraints", {}).get("circulation_min", DEFAULT_CIRCULATION_MIN_MM)
    )

    by_room: dict[str, list[dict[str, Any]]] = {}
    for proposal in proposals:
        by_room.setdefault(proposal["room_id"], []).append(proposal)

    furniture: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []
    diags: list[ItemDiag] = []
    all_aabbs: list[tuple[float, float, float, float]] = []

    for room_id in sorted(by_room):
        room = rooms_by_id[room_id]
        polygon = Polygon(room["boundary"])
        ctx = _RoomCtx(
            room=room,
            polygon=polygon,
            room_cover=polygon.buffer(0.01),
            arcs=[arc for _d, arc in room_swing_arcs(room, polygon, layout["doors"], walls_by_id)],
            thresholds=room_thresholds(room, polygon, layout["doors"], walls_by_id),
            circulation_min=circulation_min,
            placed=[],
        )
        # normalize BEFORE sorting: geometry comes from the catalog, never the
        # proposal (the LLM proposes what goes where, not shapes)
        normalized: list[dict[str, Any]] = []
        for proposal in by_room[room_id]:
            spec = family_types().get((proposal["revit_family"], proposal["revit_type"]))
            if spec is None:  # defensive: proposal validation runs upstream
                reason = "unknown catalog family/type"
                diags.append(ItemDiag(item_id=proposal["id"], room_id=room_id, reason=reason))
                unplaced.append({"item": proposal, "room_id": room_id, "reason": reason})
                continue
            normalized.append(
                {
                    **proposal,
                    "footprint": list(spec["footprint_mm"]),
                    "clearance_front": spec["clearance_front_mm"],
                    "wall_seeking": bool(
                        proposal.get("wall_seeking", spec["wall_seeking_default"])
                    ),
                }
            )
        ordered = sorted(
            normalized,
            key=lambda p: (-(p["footprint"][0] * p["footprint"][1]), p["id"]),
        )
        for proposal in ordered:
            diag = ItemDiag(item_id=proposal["id"], room_id=room_id)
            diags.append(diag)
            base_free = room_free_space(polygon, [item for item, _r, _b in ctx.placed])
            if proposal["wall_seeking"]:
                placed = _place_wall_seeking(proposal, ctx, walls_by_id, base_free, all_aabbs, diag)
            else:
                placed = _place_free_standing(proposal, ctx, base_free, all_aabbs, diag)
            if placed is None:
                unplaced.append({"item": proposal, "room_id": room_id, "reason": diag.reason})
                continue
            ctx.placed.append((placed, furniture_rect(placed), clearance_blob(placed)))
            all_aabbs.append(
                aabb_of(tuple(placed["center"]), placed["rotation_deg"], placed["footprint"])
            )
        if ctx.placed:
            furniture.append(
                {
                    "room_id": room_id,
                    "items": sorted((item for item, _r, _b in ctx.placed), key=lambda i: i["id"]),
                }
            )

    return FurnishOutcome(
        furniture=furniture,
        unplaced=unplaced,
        diagnostics={
            "items": [vars(d) for d in diags],
            "total_candidates": sum(d.candidates_tried for d in diags),
            "spiral_total": sum(d.spiral_tried for d in diags),
            "walls_tried": sum(d.walls_tried for d in diags),
        },
    )
