"""Pipe/conduit path classification — the Python twin of ChapterHub.Core PipePath,
both pinned by packages/contracts/fixtures/pipepath/manifest.json: consecutive
collinear segments merge; a bend within 0.5° of 90 or 45 is a standard elbow; any
other bend is `fitting_unsupported` (v1 emits REVIEW for tees/wyes); a segment
shorter than 1e-6 mm is `zero_length`; fewer than two points is `too_few_points`."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from typing import Any

from layout_compiler.catalogs import CONTRACTS_DIR

Pt3 = tuple[float, float, float]


class FittingError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class PathClass:
    segments: int
    bends_deg: tuple[int, ...]
    points: tuple[Pt3, ...]  # after collinear merging


@cache
def manifest() -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / "fixtures" / "pipepath" / "manifest.json").read_text())


def _angle_deg(u: Pt3, v: Pt3) -> float:
    dot = sum(a * b for a, b in zip(u, v, strict=False))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    cos = max(-1.0, min(1.0, dot / (nu * nv)))
    return math.degrees(math.acos(cos))


def classify_path(path: list[list[float]] | list[Pt3]) -> PathClass:
    spec = manifest()
    angle_tol = float(spec["angle_tolerance_deg"])
    collinear_tol = float(spec["collinear_tolerance_deg"])
    min_seg = float(spec["min_segment_mm"])
    pts: list[Pt3] = [(float(p[0]), float(p[1]), float(p[2])) for p in path]
    if len(pts) < 2:
        raise FittingError("too_few_points", f"{len(pts)} point(s)")
    for a, b in zip(pts, pts[1:], strict=False):
        if math.dist(a, b) < min_seg:
            raise FittingError("zero_length", f"segment at {a}")
    merged: list[Pt3] = [pts[0]]
    for i in range(1, len(pts) - 1):
        u = tuple(b - a for a, b in zip(merged[-1], pts[i], strict=False))
        v = tuple(b - a for a, b in zip(pts[i], pts[i + 1], strict=False))
        if _angle_deg(u, v) <= collinear_tol:  # type: ignore[arg-type]
            continue  # drop the interior point: collinear run
        merged.append(pts[i])
    merged.append(pts[-1])
    bends: list[int] = []
    for i in range(1, len(merged) - 1):
        u = tuple(b - a for a, b in zip(merged[i - 1], merged[i], strict=False))
        v = tuple(b - a for a, b in zip(merged[i], merged[i + 1], strict=False))
        angle = _angle_deg(u, v)  # type: ignore[arg-type]
        if abs(angle - 90.0) <= angle_tol:
            bends.append(90)
        elif abs(angle - 45.0) <= angle_tol:
            bends.append(45)
        else:
            raise FittingError("fitting_unsupported", f"{angle:.1f} deg bend at {merged[i]}")
    return PathClass(segments=len(merged) - 1, bends_deg=tuple(bends), points=tuple(merged))


def split_unsupported(path: list[Pt3]) -> tuple[list[list[Pt3]], int]:
    """Split a polyline at every bend that is neither 90 nor 45 (after collinear
    merging) so each piece is a legal v1 conduit/pipe; returns (pieces, splits)."""
    spec = manifest()
    angle_tol = float(spec["angle_tolerance_deg"])
    collinear_tol = float(spec["collinear_tolerance_deg"])
    pts = [tuple(float(c) for c in p) for p in path]
    merged: list[Pt3] = [pts[0]]  # type: ignore[list-item]
    for i in range(1, len(pts) - 1):
        u = tuple(b - a for a, b in zip(merged[-1], pts[i], strict=False))
        v = tuple(b - a for a, b in zip(pts[i], pts[i + 1], strict=False))
        if _angle_deg(u, v) <= collinear_tol:  # type: ignore[arg-type]
            continue
        merged.append(pts[i])  # type: ignore[arg-type]
    merged.append(pts[-1])  # type: ignore[arg-type]
    pieces: list[list[Pt3]] = [[merged[0]]]
    splits = 0
    for i in range(1, len(merged) - 1):
        u = tuple(b - a for a, b in zip(merged[i - 1], merged[i], strict=False))
        v = tuple(b - a for a, b in zip(merged[i], merged[i + 1], strict=False))
        angle = _angle_deg(u, v)  # type: ignore[arg-type]
        pieces[-1].append(merged[i])
        if not (abs(angle - 90.0) <= angle_tol or abs(angle - 45.0) <= angle_tol):
            splits += 1
            pieces.append([merged[i]])
    pieces[-1].append(merged[-1])
    return pieces, splits
