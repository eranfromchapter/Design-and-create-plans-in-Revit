"""Shared placement math (Part G projection primitive specialized to offset-along-wall).

Pinned against packages/contracts/fixtures/placement/manifest.json — the C# twin is
ChapterHub.Core.Placement; the Phase 1 acceptance requires both to agree to 1e-6 mm.
"""

from __future__ import annotations

import math

Pt2 = tuple[float, float]


def _unit(start: Pt2, end: Pt2) -> Pt2:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("zero-length wall")
    return dx / length, dy / length


def centerline_point(start: Pt2, end: Pt2, offset_mm: float) -> Pt2:
    ux, uy = _unit(start, end)
    return start[0] + ux * offset_mm, start[1] + uy * offset_mm


def face_point(start: Pt2, end: Pt2, thickness_mm: float, offset_mm: float, side: str) -> Pt2:
    """side: 'left' | 'right' of the start->end direction; left = +90deg CCW."""
    cx, cy = centerline_point(start, end, offset_mm)
    ux, uy = _unit(start, end)
    nx, ny = -uy, ux  # left normal
    if side == "right":
        nx, ny = -nx, -ny
    elif side != "left":
        raise ValueError(f"unknown side {side!r}")
    half = thickness_mm / 2.0
    return cx + nx * half, cy + ny * half


def place(
    kind: str,
    start: Pt2,
    end: Pt2,
    thickness_mm: float,
    offset_mm: float,
    z_mm: float,
) -> tuple[float, float, float]:
    """kind: 'centerline' | 'face_left' | 'face_right' (the fixture vocabulary)."""
    if kind == "centerline":
        x, y = centerline_point(start, end, offset_mm)
    elif kind in ("face_left", "face_right"):
        x, y = face_point(start, end, thickness_mm, offset_mm, kind.removeprefix("face_"))
    else:
        raise ValueError(f"unknown placement kind {kind!r}")
    return x, y, z_mm
