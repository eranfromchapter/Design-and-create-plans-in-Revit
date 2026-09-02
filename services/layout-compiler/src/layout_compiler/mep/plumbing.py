"""P-1..P-4 (PLAN.md Part G, docs/PHASE6_DESIGN.md §3.2, PIN-04..11): wet-wall
selection by ΣFU with the riser bias, fixture projection, FU-weighted stack
position snapped out of door spans, size-dependent slope feasibility with prune-
and-re-run, and the per-stack Manhattan branch TREE (one create_pipe per unique
segment, Ø = max upstream, honest z-profile). Deterministic; every loop bounded
(MAX_STACKS, MAX_P1_ITERATIONS, len(serve)); the deadline callback is polled per
outer iteration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from layout_compiler.catalogs import drain_slope
from layout_compiler.geometry import pt_on_wall, wall_len
from layout_compiler.interior import project_to_wall
from layout_compiler.mep.constants import (
    COORD_ROUND,
    LAMBDA_FU_PER_MM,
    MAX_P1_ITERATIONS,
    MAX_STACKS,
    P1_EXCLUDE_SI8_WALLS,
    P4_L_INCLUDES_DRAIN_LEG,
    RISER_ADJACENT_MM,
    STACK_MIN_DIAMETER_MM,
    STACK_SNAP_MARGIN_MM,
    STACK_WC_DIAMETER_MM,
)
from layout_compiler.mep.inputs import (
    DeadlineCheck,
    Fixture,
    MepInputs,
    ReviewItem,
    offset_of,
    point_distance_to_wall,
    si8_flagged,
)

Pt = tuple[float, float]


@dataclass
class Stack:
    id: str
    wall_id: str
    offset: float
    xy: Pt
    diameter: float
    fixture_ids: list[str]
    score_fu: float
    riser_bias: float
    p1_ranking: list[tuple[str, float]]
    snapped: bool
    feet: dict[str, float]  # fixture id -> offset of its P-2 foot along the wall

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "wall_id": self.wall_id,
            "offset": round(self.offset, COORD_ROUND),
            "xy": [round(self.xy[0], COORD_ROUND), round(self.xy[1], COORD_ROUND)],
            "diameter": self.diameter,
            "fixtures": list(self.fixture_ids),
            "score_fu": round(self.score_fu, 4),
            "riser_bias": round(self.riser_bias, 4),
            "p1_ranking": [[w, round(s, 4)] for w, s in self.p1_ranking],
            "snapped": self.snapped,
        }


@dataclass
class Segment:
    id: str
    stack_id: str
    fixture_ids: list[str]
    diameter: float
    slope: float
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    cls: str  # "leg" | "along"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stack_id": self.stack_id,
            "fixture_ids": list(self.fixture_ids),
            "diameter": self.diameter,
            "slope": self.slope,
            "segment": [list(self.start), list(self.end)],
            "cls": self.cls,
        }


@dataclass
class PlumbingResult:
    stacks: list[Stack]
    segments: list[Segment]
    fixture_routes: list[dict[str, Any]]
    items: list[ReviewItem]
    counters: dict[str, int] = field(default_factory=dict)


def l_max_mm(h_plenum: float, drain_mm: float, h_fitting: float) -> float:
    """P-4: L_max = (h_plenum − Ø − h_fitting) / s, slope by drain diameter."""
    return (h_plenum - drain_mm - h_fitting) / drain_slope(drain_mm)


def stack_diameter(fixtures: list[Fixture]) -> float:
    d = max([STACK_MIN_DIAMETER_MM, *(f.drain_mm for f in fixtures)])
    if any(f.kind == "wc" for f in fixtures):
        d = max(d, STACK_WC_DIAMETER_MM)
    return d


def _door_spans(layout: dict[str, Any], wall_id: str, margin: float) -> list[tuple[float, float]]:
    return [
        (d["offset"] - d["width"] / 2 - margin, d["offset"] + d["width"] / 2 + margin)
        for d in layout["doors"]
        if d["host_wall_id"] == wall_id
    ]


def snap_out_of_door_spans(
    offset: float, wall: dict[str, Any], layout: dict[str, Any], margin: float
) -> float | None:
    """PIN-07: a stack inside a door clear span (± Ø/2 + 50) moves to the nearest legal
    offset on the wall; None when no legal offset remains."""
    length = wall_len(wall)
    spans = _door_spans(layout, wall["id"], margin)
    lo, hi = margin, length - margin
    if hi < lo:
        return None

    def legal(t: float) -> bool:
        return lo <= t <= hi and not any(a < t < b for a, b in spans)

    if legal(offset):
        return offset
    candidates = [c for a, b in spans for c in (a, b) if legal(c)]
    for edge in (lo, hi):
        if legal(edge):
            candidates.append(edge)
    if not candidates:
        return None
    return min(candidates, key=lambda c: (abs(c - offset), c))


def _riser_distance(wall: dict[str, Any], layout: dict[str, Any]) -> float | None:
    risers = [r for r in layout.get("risers", []) if r["type"] == "sanitary"]
    if not risers:
        return None
    return min(point_distance_to_wall((r["center"][0], r["center"][1]), wall) for r in risers)


def plan_plumbing(
    inputs: MepInputs,
    deadline_check: DeadlineCheck = None,
    banned_walls: Iterable[str] = (),
) -> PlumbingResult:
    """`banned_walls` (merge-gate relocate_stack): walls that never become P-1
    candidates for this run — unlike the per-iteration exclusions, they persist."""
    layout = inputs.layout
    items: list[ReviewItem] = []
    counters = {"p1_iterations": 0, "p4_prune_steps": 0, "snap_steps": 0}
    stacks: list[Stack] = []
    segments: list[Segment] = []
    routes: list[dict[str, Any]] = []
    fixtures = {f.id: f for f in inputs.fixtures}
    if inputs.h_plenum is None or inputs.blocking():
        # levels missing/inconsistent or an unknown fixture kind: no plumbing plan yet
        return PlumbingResult(stacks, segments, routes, items, counters)
    h_plenum, h_fitting = inputs.h_plenum, inputs.h_fitting
    residual = set(fixtures)
    excluded: set[str] = set()
    banned = set(banned_walls)
    iteration = 0
    while residual:
        if deadline_check:
            deadline_check()
        iteration += 1
        if iteration > MAX_P1_ITERATIONS:
            items.append(
                ReviewItem(
                    "p1_iterations_exceeded",
                    "blocking",
                    sorted(residual),
                    f"P-1 did not converge within {MAX_P1_ITERATIONS} iterations",
                )
            )
            break
        if len(stacks) >= MAX_STACKS:
            items.append(
                ReviewItem(
                    "stacks_exceeded",
                    "blocking",
                    sorted(residual),
                    f"more than {MAX_STACKS} stacks needed",
                )
            )
            break
        counters["p1_iterations"] = iteration
        # ---- P-1: candidates = walls bounding a wet room with >= 1 residual fixture
        cand: dict[str, set[str]] = {}
        for room_id in inputs.wet_rooms:
            room_fixtures = {f.id for f in fixtures.values() if f.room_id == room_id} & residual
            if not room_fixtures:
                continue
            for wall_id in inputs.rooms[room_id]["boundary_wall_ids"]:
                wall = inputs.walls[wall_id]
                if wall_id in excluded or wall_id in banned:
                    continue
                if P1_EXCLUDE_SI8_WALLS and si8_flagged(wall):
                    continue
                cand.setdefault(wall_id, set()).update(room_fixtures)
        if not cand:
            items.append(
                ReviewItem(
                    "no_wet_wall_candidate",
                    "blocking",
                    sorted(residual),
                    "no wall bounds a wet room holding these fixtures (or all are SI-8 flagged)",
                )
            )
            break
        scored: list[tuple[tuple[float, bool, float, int], str, float, float]] = []
        for wall_id, ids in cand.items():
            wall = inputs.walls[wall_id]
            fu = sum(fixtures[i].fixture_units for i in ids)
            riser_d = _riser_distance(wall, layout)
            bias = LAMBDA_FU_PER_MM * riser_d if riser_d is not None else 0.0
            score = fu - bias
            fixture_dist = sum(
                fixtures[i].fixture_units * point_distance_to_wall(fixtures[i].center, wall)
                for i in ids
            )
            key = (
                round(score, 9),
                bool(wall.get("is_wet_wall")),
                -round(fixture_dist, 6),
                -int(wall_id.split("-")[1]),
            )  # PIN-06: higher score, wet wall first, closer fixtures, smaller id
            scored.append((key, wall_id, score, bias))
        scored.sort(key=lambda s: s[0], reverse=True)
        _key, pick, score, bias = scored[0]
        ranking = [(w, s) for _k, w, s, _b in scored[:5]]
        wall = inputs.walls[pick]
        length = wall_len(wall)
        serve: list[str] = sorted(cand[pick])
        # ---- P-2 / P-3 / P-4 prune loop (bounded by len(serve))
        stack_offset: float | None = None
        snapped = False
        feet: dict[str, float] = {}
        while serve:
            feet = {}
            for fid in serve:
                t_star, _foot = project_to_wall(fixtures[fid].center, wall)
                feet[fid] = t_star * length
            total_fu = sum(fixtures[f].fixture_units for f in serve)
            t_s = sum(fixtures[f].fixture_units * feet[f] for f in serve) / total_fu
            diameter = stack_diameter([fixtures[f] for f in serve])
            snapped_offset = snap_out_of_door_spans(
                t_s, wall, layout, diameter / 2 + STACK_SNAP_MARGIN_MM
            )
            if snapped_offset is None:
                stack_offset = None
                break
            if abs(snapped_offset - t_s) > 1e-9:
                snapped = True
                counters["snap_steps"] += 1
            stack_offset = snapped_offset
            violations: list[tuple[float, int, str]] = []
            for fid in serve:
                along = abs(feet[fid] - stack_offset)
                leg = point_distance_to_wall(fixtures[fid].center, wall)
                routed = along + (leg if P4_L_INCLUDES_DRAIN_LEG else 0.0)
                limit = l_max_mm(h_plenum, fixtures[fid].drain_mm, h_fitting)
                if routed > limit + 1e-9:
                    violations.append((routed, -int(fid.split("-")[1]), fid))
            if not violations:
                break
            violations.sort(reverse=True)  # largest routed L, then smaller id
            dropped = violations[0][2]
            serve.remove(dropped)
            counters["p4_prune_steps"] += 1
            items.append(
                ReviewItem(
                    "p4_prune",
                    "info",
                    [dropped, pick],
                    f"{dropped}: routed branch {violations[0][0]:.0f} mm exceeds L_max on "
                    f"{pick}; served by a later stack",
                )
            )
        if stack_offset is None or not serve:
            excluded.add(pick)
            if snapped:
                counters["snap_steps"] += 0
            continue
        stack_id = f"P-{len(stacks) + 1:03d}"
        xy = pt_on_wall(wall, stack_offset)
        stack = Stack(
            id=stack_id,
            wall_id=pick,
            offset=stack_offset,
            xy=(xy[0], xy[1]),
            diameter=stack_diameter([fixtures[f] for f in serve]),
            fixture_ids=list(serve),
            score_fu=score,
            riser_bias=bias,
            p1_ranking=ranking,
            snapped=snapped,
            feet={f: feet[f] for f in serve},
        )
        stacks.append(stack)
        if snapped:
            items.append(
                ReviewItem(
                    "p3_snapped",
                    "info",
                    [stack_id],
                    f"{stack_id}: FU-weighted position fell in a door span on {pick}; "
                    f"snapped to offset {stack_offset:.1f}",
                )
            )
        riser_d = _riser_distance(wall, layout)
        if riser_d is not None and riser_d <= RISER_ADJACENT_MM:
            items.append(
                ReviewItem(
                    "riser_adjacent",
                    "info",
                    [stack_id],
                    f"{stack_id} lies within {RISER_ADJACENT_MM:.0f} mm of an existing "
                    "sanitary riser (v1 does not adopt risers)",
                )
            )
        residual -= set(serve)
        excluded.clear()  # a new residual set re-opens every wall (spec: re-run P-1)

    # ---- branch trees + routes
    next_pipe = len(stacks) + 1
    for stack in stacks:
        tree, next_pipe = _branch_tree(stack, fixtures, inputs, next_pipe, items, routes)
        segments.extend(tree)
    manual = (("vent", "vent_manual"), ("supply_h", "supply_manual"), ("gas", "gas_manual"))
    for hookup, code in manual:
        refs = sorted(f.id for f in inputs.fixtures if hookup in (f.item.get("hookups") or []))
        if refs:
            items.append(
                ReviewItem(
                    code,
                    "info",
                    refs,
                    f"v1 emits sanitary DWV only; {hookup} connections are completed manually",
                )
            )
    return PlumbingResult(stacks, segments, routes, items, counters)


def _key(p: tuple[float, float]) -> tuple[float, float]:
    return (round(p[0], COORD_ROUND), round(p[1], COORD_ROUND))


def _branch_tree(
    stack: Stack,
    fixtures: dict[str, Fixture],
    inputs: MepInputs,
    next_pipe: int,
    items: list[ReviewItem],
    routes: list[dict[str, Any]],
) -> tuple[list[Segment], int]:
    """PIN-10: paths centre -> foot -> stack, unioned and split at every node; one
    segment per unique edge, Ø = max drain upstream, slope by Ø; z walked outward
    from the stack junction so the governing fixture's pipe top sits at
    floor_z − h_fitting; per-segment plenum check -> info branch_plenum_marginal."""
    wall = inputs.walls[stack.wall_id]
    floor_z, h_plenum, h_fitting = inputs.floor_z, inputs.h_plenum or 0.0, inputs.h_fitting
    stack_node = _key(stack.xy)
    # raw edges per fixture path (as ordered node lists from the fixture outward to the stack)
    paths: dict[str, list[tuple[float, float]]] = {}
    for fid in stack.fixture_ids:
        f = fixtures[fid]
        foot = _key(pt_on_wall(wall, stack.feet[fid]))
        centre = _key(f.center)
        nodes = [centre]
        if foot != centre:
            nodes.append(foot)
        if stack_node != nodes[-1]:
            nodes.append(stack_node)
        paths[fid] = nodes
    # split every edge at nodes lying on it (collinear, strictly between endpoints)
    all_nodes = {n for nodes in paths.values() for n in nodes}
    refined: dict[str, list[tuple[float, float]]] = {}
    for fid, nodes in paths.items():
        out = [nodes[0]]
        for a, b in zip(nodes, nodes[1:], strict=False):
            between = [n for n in all_nodes if n not in (a, b) and _on_segment(n, a, b)]
            between.sort(key=lambda n: _param(n, a, b))
            out.extend(between)
            out.append(b)
        refined[fid] = out
    # unique edges with their users; classify leg (perpendicular) vs along (on the wall)
    edges: dict[tuple[tuple[float, float], tuple[float, float]], set[str]] = {}
    order: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for fid in sorted(refined):
        for a, b in zip(refined[fid], refined[fid][1:], strict=False):
            edge = (a, b) if (a, b) in edges else ((b, a) if (b, a) in edges else (a, b))
            if edge not in edges:
                edges[edge] = set()
                order.append(edge)
            edges[edge].add(fid)
    # z-profile: rise of each fixture along its path from the stack outward
    seg_slope = {
        e: drain_slope(max(fixtures[f].drain_mm for f in users)) for e, users in edges.items()
    }
    seg_diam = {e: max(fixtures[f].drain_mm for f in users) for e, users in edges.items()}

    def edge_of(a: tuple[float, float], b: tuple[float, float]):
        return (a, b) if (a, b) in edges else (b, a)

    rises: dict[str, float] = {}
    for fid, nodes in refined.items():
        rises[fid] = sum(
            seg_slope[edge_of(a, b)] * _dist(a, b) for a, b in zip(nodes, nodes[1:], strict=False)
        )
    governing = max(sorted(rises), key=lambda f: (rises[f], -int(f.split("-")[1])))
    z_junction = floor_z - h_fitting - fixtures[governing].drain_mm / 2 - rises[governing]
    # node z by walking outward from the stack along each path (a tree: consistent)
    node_z: dict[tuple[float, float], float] = {stack_node: z_junction}
    for nodes in refined.values():
        z = z_junction
        for a, b in zip(reversed(nodes), list(reversed(nodes))[1:], strict=False):
            z = z + seg_slope[edge_of(a, b)] * _dist(a, b)
            node_z.setdefault(b, z)
    segments: list[Segment] = []
    marginal: dict[str, float] = {}
    for edge in order:
        a, b = edge
        users = sorted(edges[edge])
        diameter = seg_diam[edge]
        # orient each segment stack-ward: start = farther from the stack (higher z)
        if node_z[a] < node_z[b]:
            a, b = b, a
        cls = "along" if _on_wall_line(a, wall) and _on_wall_line(b, wall) else "leg"
        seg = Segment(
            id=f"P-{next_pipe:03d}",
            stack_id=stack.id,
            fixture_ids=users,
            diameter=diameter,
            slope=seg_slope[edge],
            start=(a[0], a[1], round(node_z[a], COORD_ROUND)),
            end=(b[0], b[1], round(node_z[b], COORD_ROUND)),
            cls=cls,
        )
        next_pipe += 1
        segments.append(seg)
        bottom = min(node_z[a], node_z[b]) - diameter / 2
        if bottom < floor_z - h_plenum - 1e-9:
            for fid in users:
                marginal[fid] = max(marginal.get(fid, 0.0), (floor_z - h_plenum) - bottom)
    for fid in sorted(marginal):
        items.append(
            ReviewItem(
                "branch_plenum_marginal",
                "info",
                [fid, stack.id],
                f"{fid}: branch bottom overshoots the plenum by {marginal[fid]:.1f} mm "
                "(spec-literal P-4 accepts the along-wall length; verify on site)",
            )
        )
    junctions = sum(1 for n in all_nodes if sum(1 for e in edges if n in e) >= 3) + (
        1 if any(stack_node in e for e in edges) else 0
    )
    if junctions:
        items.append(
            ReviewItem(
                "wye_manual",
                "info",
                [stack.id],
                f"{stack.id}: {junctions} tee/wye junction(s) to complete manually (registry: "
                "standard elbows only in v1)",
            )
        )
    for fid in stack.fixture_ids:
        f = fixtures[fid]
        along = abs(stack.feet[fid] - stack.offset)
        leg = point_distance_to_wall(f.center, wall)
        routes.append(
            {
                "fixture_id": fid,
                "stack_id": stack.id,
                "leg_mm": round(leg, COORD_ROUND),
                "along_mm": round(along, COORD_ROUND),
                "L_mm": round(along + (leg if P4_L_INCLUDES_DRAIN_LEG else 0.0), COORD_ROUND),
                "L_max_mm": round(l_max_mm(h_plenum, f.drain_mm, inputs.h_fitting), COORD_ROUND),
                "path_mm": round(leg + along, COORD_ROUND),
                "plenum_overshoot_mm": round(marginal.get(fid, 0.0), COORD_ROUND),
            }
        )
    return segments, next_pipe


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _param(n: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    d = _dist(a, b)
    if d == 0:
        return 0.0
    return ((n[0] - a[0]) * (b[0] - a[0]) + (n[1] - a[1]) * (b[1] - a[1])) / (d * d)


def _on_segment(n: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    d = _dist(a, b)
    if d == 0:
        return False
    cross = abs((b[0] - a[0]) * (n[1] - a[1]) - (b[1] - a[1]) * (n[0] - a[0])) / d
    t = _param(n, a, b)
    return cross <= 0.5 and 1e-9 < t < 1 - 1e-9


def _on_wall_line(p: tuple[float, float], wall: dict[str, Any]) -> bool:
    if point_distance_to_wall(p, wall) > 0.5:
        return False
    return 0.0 <= offset_of(p, wall) <= wall_len(wall) + 0.5
