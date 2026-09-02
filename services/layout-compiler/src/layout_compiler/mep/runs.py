"""Wall runs (docs/PHASE6_DESIGN.md §3.1): the continuous stretches of a room's
wall at a device height, i.e. the room's collinear boundary edges on that wall
minus openings (doors always; windows only when the device height lies within the
window, PIN-12), minus explicit extra breaks (counter intervals for E-1), minus
stack exclusion zones only when ZONES_BREAK_DEVICE_RUNS (PIN-13)."""

from __future__ import annotations

from typing import Any

from layout_compiler.geometry import wall_len
from layout_compiler.mep.constants import (
    COORD_ROUND,
    DEVICE_EDGE_MM,
    WINDOWS_BREAK_RUNS_ALWAYS,
    ZONES_BREAK_DEVICE_RUNS,
)
from layout_compiler.mep.inputs import _merge, _subtract, offset_of, unit_along, wall_thickness

Interval = tuple[float, float]


def room_edges_on_wall(room: dict[str, Any], wall: dict[str, Any]) -> list[Interval]:
    """Offsets along the wall covered by the room's boundary edges that lie on this
    wall's centerline (both endpoints within t/2 + 1 mm of the infinite line)."""
    ux, uy = unit_along(wall)
    sx, sy = wall["start"]
    tol = wall_thickness(wall) / 2 + 1.0
    length = wall_len(wall)
    ring = [*room["boundary"], room["boundary"][0]]
    out: list[Interval] = []
    for a, b in zip(ring, ring[1:], strict=False):
        da = abs((a[0] - sx) * uy - (a[1] - sy) * ux)
        db = abs((b[0] - sx) * uy - (b[1] - sy) * ux)
        if da > tol or db > tol:
            continue
        ta, tb = offset_of((a[0], a[1]), wall), offset_of((b[0], b[1]), wall)
        t0, t1 = max(0.0, min(ta, tb)), min(length, max(ta, tb))
        if t1 - t0 > 1.0:
            out.append((t0, t1))
    return _merge(out)


def opening_breaks(layout: dict[str, Any], wall_id: str, height_afl: float) -> list[Interval]:
    breaks: list[Interval] = []
    for door in layout["doors"]:
        if door["host_wall_id"] == wall_id:
            breaks.append((door["offset"] - door["width"] / 2, door["offset"] + door["width"] / 2))
    for window in layout["windows"]:
        if window["host_wall_id"] != wall_id:
            continue
        sill = float(window["sill_height"])
        if WINDOWS_BREAK_RUNS_ALWAYS or sill <= height_afl <= sill + float(window["height"]):
            breaks.append(
                (window["offset"] - window["width"] / 2, window["offset"] + window["width"] / 2)
            )
    return breaks


def wall_runs(
    layout: dict[str, Any],
    room: dict[str, Any],
    wall: dict[str, Any],
    height_afl: float,
    zones: list[Interval] | tuple[Interval, ...] = (),
    extra_breaks: list[Interval] | tuple[Interval, ...] = (),
) -> list[Interval]:
    segments = room_edges_on_wall(room, wall)
    breaks = opening_breaks(layout, wall["id"], height_afl) + list(extra_breaks)
    if ZONES_BREAK_DEVICE_RUNS:
        breaks += list(zones)
    runs = _subtract(segments, breaks)
    return [(round(a, COORD_ROUND), round(b, COORD_ROUND)) for a, b in runs if b - a > 1.0]


def legal_on_runs(runs: list[Interval], offset: float, edge: float = DEVICE_EDGE_MM) -> bool:
    return any(t0 + edge <= offset <= t1 - edge for t0, t1 in runs)


def run_containing(runs: list[Interval], offset: float) -> Interval | None:
    for t0, t1 in runs:
        if t0 <= offset <= t1:
            return (t0, t1)
    return None
