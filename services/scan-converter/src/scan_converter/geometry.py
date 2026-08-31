"""Pure-math 2D geometry for Lane A: bulge tessellation, heading snap, endpoint
merge, point/segment projection. No shapely/numpy — float determinism protects
the Phase 2 golden SVG (same rule as the sim's renderer)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Pt = tuple[float, float]


@dataclass
class RawWall:
    start: Pt
    end: Pt
    thickness: float
    curved: bool = False  # chord of a tessellated arc
    skewed: bool = False  # heading beyond snap tolerance (set by snap_headings)
    skew_deg: float = 0.0
    notes: dict = field(default_factory=dict)  # review-flag details (radius, chord i/n, ...)

    @property
    def length(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    def heading_deg(self) -> float:
        return math.degrees(math.atan2(self.end[1] - self.start[1], self.end[0] - self.start[0]))


def tessellate_bulge(p1: Pt, p2: Pt, bulge: float, max_sagitta: float) -> list[Pt]:
    """Chord-chain vertices from p1 to p2 (p1 excluded, p2 included, exact).

    DXF bulge = tan(theta/4); positive = CCW from p1 to p2. Max sagitta bounds the
    true-arc deviation of every chord (PLAN.md Phase 2: 10 mm)."""
    theta = 4.0 * math.atan(abs(bulge))
    chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if theta == 0.0 or chord == 0.0:
        return [p2]
    radius = chord / (2.0 * math.sin(theta / 2.0))
    if radius <= max_sagitta:
        return [p2]
    delta_max = 2.0 * math.acos(1.0 - max_sagitta / radius)
    n = math.ceil(theta / delta_max - 1e-12)
    if n <= 1:
        return [p2]

    mx, my = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
    ux, uy = (p2[0] - p1[0]) / chord, (p2[1] - p1[1]) / chord
    # left normal of p1->p2; the center sits on the left for CCW (bulge > 0)
    nx, ny = -uy, ux
    apothem = radius * math.cos(theta / 2.0)
    side = 1.0 if bulge > 0 else -1.0
    cx, cy = mx + side * nx * apothem, my + side * ny * apothem

    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    sweep = side * theta
    points: list[Pt] = []
    for i in range(1, n):
        ang = a1 + sweep * (i / n)
        points.append((cx + radius * math.cos(ang), cy + radius * math.sin(ang)))
    points.append(p2)
    return points


def arc_params(p1: Pt, p2: Pt, bulge: float) -> tuple[float, float]:
    """(radius, included angle deg) of a bulge arc — for review-flag details."""
    theta = 4.0 * math.atan(abs(bulge))
    chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    return chord / (2.0 * math.sin(theta / 2.0)), math.degrees(theta)


def _offset_to_axis(heading_deg: float, axis_deg: float) -> float:
    """Signed distance (deg) from a heading to the nearest axis multiple, in (-45, 45]."""
    return ((heading_deg - axis_deg + 45.0) % 90.0) - 45.0


def dominant_axis_deg(walls: list[RawWall]) -> float:
    """Length-weighted mode of straight-wall headings mod 90 (0.5 deg bins), refined
    by the weighted MEDIAN within +-1.5 deg of the winning bin's center. The median
    (not mean) keeps the axis EXACT when most length is exactly orthogonal — the
    snap-exactness acceptance test depends on this."""
    straight = [w for w in walls if not w.curved and w.length > 0]
    if not straight:
        return 0.0
    bins: dict[int, float] = {}
    for w in straight:
        h = w.heading_deg() % 90.0
        bins[int(h / 0.5) % 180] = bins.get(int(h / 0.5) % 180, 0.0) + w.length
    best_bin = min(bins, key=lambda b: (-bins[b], b))
    center = best_bin * 0.5 + 0.25

    members: list[tuple[float, float]] = []  # (offset from center, weight)
    for w in straight:
        off = _offset_to_axis(w.heading_deg() % 90.0, center)
        if abs(off) <= 1.5:
            members.append((off, w.length))
    members.sort()
    total = sum(weight for _, weight in members)
    acc = 0.0
    median_off = members[-1][0]
    for off, weight in members:
        acc += weight
        if acc >= total / 2.0:
            median_off = off
            break
    return (center + median_off) % 90.0


def snap_headings(walls: list[RawWall], axis_deg: float, tol_deg: float) -> None:
    """Rotate near-axis walls to the exact axis by projecting both endpoints onto
    the snapped-heading line through the wall midpoint (exactly-on-axis walls are
    untouched). Beyond tolerance: preserved + skewed flag. Chords are exempt."""
    for w in walls:
        if w.curved or w.length == 0:
            continue
        delta = _offset_to_axis(w.heading_deg() % 90.0, axis_deg)
        if delta == 0.0:
            continue
        if abs(delta) > tol_deg:
            w.skewed = True
            w.skew_deg = abs(delta)
            continue
        snapped = w.heading_deg() - delta
        dx, dy = math.cos(math.radians(snapped)), math.sin(math.radians(snapped))
        # canonicalize exact orthogonals so vertical/horizontal snaps are bit-exact
        if abs(dx) < 1e-9:
            dx, dy = 0.0, math.copysign(1.0, dy)
        elif abs(dy) < 1e-9:
            dx, dy = math.copysign(1.0, dx), 0.0
        mx, my = (w.start[0] + w.end[0]) / 2.0, (w.start[1] + w.end[1]) / 2.0
        for attr in ("start", "end"):
            px, py = getattr(w, attr)
            t = (px - mx) * dx + (py - my) * dy
            setattr(w, attr, (mx + t * dx, my + t * dy))


def merge_endpoints(walls: list[RawWall], min_tol: float) -> None:
    """Corner closure: cluster wall endpoints that lie within
    max(max(thickness)/2, min_tol) of each other and move every member to the
    cluster centroid. Union-find over (wall index, end index), deterministic."""
    nodes: list[tuple[int, int, Pt, float]] = []
    for wi, w in enumerate(walls):
        nodes.append((wi, 0, w.start, w.thickness))
        nodes.append((wi, 1, w.end, w.thickness))

    parent = list(range(len(nodes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if nodes[i][0] == nodes[j][0]:
                continue
            tol = max(max(nodes[i][3], nodes[j][3]) / 2.0, min_tol)
            (x1, y1), (x2, y2) = nodes[i][2], nodes[j][2]
            if math.hypot(x1 - x2, y1 - y2) <= tol:
                parent[find(i)] = find(j)

    clusters: dict[int, list[int]] = {}
    for i in range(len(nodes)):
        clusters.setdefault(find(i), []).append(i)
    for members in clusters.values():
        if len(members) < 2:
            continue
        pts = sorted(nodes[i][2] for i in members)
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        for i in members:
            wi, ei, _, _ = nodes[i]
            if ei == 0:
                walls[wi].start = (cx, cy)
            else:
                walls[wi].end = (cx, cy)


def project_on_segment(p: Pt, a: Pt, b: Pt) -> tuple[float, float]:
    """(distance to segment, clamped parameter in mm from a along a->b)."""
    ax, ay = a
    vx, vy = b[0] - ax, b[1] - ay
    length = math.hypot(vx, vy)
    if length == 0.0:
        return math.hypot(p[0] - ax, p[1] - ay), 0.0
    t = ((p[0] - ax) * vx + (p[1] - ay) * vy) / length
    t = min(max(t, 0.0), length)
    qx, qy = ax + vx * (t / length), ay + vy * (t / length)
    return math.hypot(p[0] - qx, p[1] - qy), t
