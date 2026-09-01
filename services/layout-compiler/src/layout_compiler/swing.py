"""Door-swing arcs (Phase 5, Part G "clear of door-swing arcs" predicate).

v1 conventions, PINNED (worked example below; conformance tests cover all four
swing x flip combinations):

- The hinge jamb sits at `offset - width/2` along the host wall's start->end
  direction for swing "L", at `offset + width/2` for swing "R" (the schema
  defines swing as the hinge side viewed along start->end from the
  flip_facing=false side; absent swing defaults to "L" like the ops builder).
- The leaf sweeps into the LEFT side of start->end when flip_facing is falsy
  (matching the registry's create_wall convention that the wall's exterior/
  finish side is the LEFT of start->end), and into the RIGHT side when true.
- The swept region is the quarter disc of radius = door width, from the closed
  leaf (lying along the wall, hinge -> other jamb) to fully open (along the
  swept-side normal): polygon = hinge + ARC_SEGMENTS+1 arc points.
- The arc constrains ONLY the single room containing the swept side (probe:
  door centerline point + 1mm along the swept-side normal).
- Pocket doors have no leaf: no arc, ever.
- t_finish = 0 in v1 (no contract field exists); arcs live on centerlines like
  every other Part G predicate.

Worked example — wall (0,0)->(3000,0), door offset 1500, width 900:
  swing "L", flip falsy: hinge (1050, 0), sweeps into y > 0
  swing "R", flip falsy: hinge (1950, 0), sweeps into y > 0 (leaf toward -x)
  either swing, flip true: same hinges, sweeps into y < 0
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import Point, Polygon

from layout_compiler.catalogs import pocket_door_types
from layout_compiler.geometry import pt_on_wall, wall_len

ARC_SEGMENTS = 16  # quarter disc sampled at 16 segments (17 arc points)


def _unit_along(wall: dict[str, Any]) -> tuple[float, float]:
    length = wall_len(wall)
    if length == 0:
        return (1.0, 0.0)
    return (
        (wall["end"][0] - wall["start"][0]) / length,
        (wall["end"][1] - wall["start"][1]) / length,
    )


def hinge_point(door: dict[str, Any], wall: dict[str, Any]) -> tuple[float, float]:
    side = -1.0 if door.get("swing", "L") == "L" else 1.0
    return pt_on_wall(wall, door["offset"] + side * door["width"] / 2)


def swing_side_normal(door: dict[str, Any], wall: dict[str, Any]) -> tuple[float, float]:
    ux, uy = _unit_along(wall)
    left = (-uy, ux)
    if door.get("flip_facing"):
        return (uy, -ux)
    return left


def door_swing_arc(door: dict[str, Any], wall: dict[str, Any]) -> Polygon | None:
    """The swept quarter disc, or None for pocket doors (no leaf)."""
    if door["revit_type"] in pocket_door_types():
        return None
    hx, hy = hinge_point(door, wall)
    ux, uy = _unit_along(wall)
    # closed leaf points from the hinge toward the other jamb
    if door.get("swing", "L") == "L":
        closed = (ux, uy)
    else:
        closed = (-ux, -uy)
    nx, ny = swing_side_normal(door, wall)
    radius = float(door["width"])
    points: list[tuple[float, float]] = [(hx, hy)]
    for i in range(ARC_SEGMENTS + 1):
        theta = (math.pi / 2) * i / ARC_SEGMENTS
        dx = math.cos(theta) * closed[0] + math.sin(theta) * nx
        dy = math.cos(theta) * closed[1] + math.sin(theta) * ny
        points.append((hx + radius * dx, hy + radius * dy))
    return Polygon(points)


def room_swing_arcs(
    room: dict[str, Any],
    room_polygon: Polygon,
    doors: list[dict[str, Any]],
    walls_by_id: dict[str, dict[str, Any]],
) -> list[tuple[str, Polygon]]:
    """The arcs constraining THIS room: doors on its boundary walls whose swept
    side lands inside the room (probe = centerline point + 1mm along the swept
    normal). A door on a shared wall constrains exactly one of its two rooms."""
    arcs: list[tuple[str, Polygon]] = []
    for door in doors:
        wall = walls_by_id.get(door["host_wall_id"])
        if wall is None or door["host_wall_id"] not in room["boundary_wall_ids"]:
            continue
        arc = door_swing_arc(door, wall)
        if arc is None:
            continue
        mx, my = pt_on_wall(wall, door["offset"])
        nx, ny = swing_side_normal(door, wall)
        if room_polygon.covers(Point(mx + nx, my + ny)):
            arcs.append((door["id"], arc))
    return arcs
