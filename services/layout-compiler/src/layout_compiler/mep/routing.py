"""E-4 home runs (PLAN.md Part G, docs/PHASE6_DESIGN.md §3.5, PIN-22/23): a
canonical wall-centerline graph (endpoints, wall intersections, device feet, panel
foot, stack-square crossings; union-find canonicalization within 1 mm), a single-
source state Dijkstra from the panel with edge cost = length + 4000·(fire-rated
or demising penetrations) and stack ±300 squares forbidden, conduits at 2600 as a
single-source raceway TREE: one drop per device plus one conduit per maximal trunk
chain. Bounded (states <= |nodes|·(|walls|+1), counter-asserted), deterministic
ties, deadline polled in the relax loop."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, box

from layout_compiler.catalogs import wall_fire_rating_hr
from layout_compiler.geometry import pt_on_wall, wall_len
from layout_compiler.mep.constants import (
    COORD_ROUND,
    E4_CONDUIT_Z_MM,
    E4_MAX_PATH_POINTS,
    E4_PENETRATION_PENALTY_MM,
    E4_STACK_EXCLUSION_MM,
    GRAPH_NODE_TOL_MM,
)
from layout_compiler.mep.electrical import Device
from layout_compiler.mep.fittings import split_unsupported
from layout_compiler.mep.inputs import DeadlineCheck, MepInputs, ReviewItem, offset_of

Node = tuple[float, float]


@dataclass
class Graph:
    nodes: list[Node]
    edges: dict[Node, list[tuple[Node, str, float]]]  # node -> [(other, wall_id, length)]
    interior_of: dict[Node, set[str]]  # node -> rated walls it lies strictly inside
    node_walls: dict[Node, set[str]]

    def counts(self) -> dict[str, int]:
        return {
            "graph_nodes": len(self.nodes),
            "graph_edges": sum(len(v) for v in self.edges.values()) // 2,
        }


@dataclass
class HomeRun:
    device_id: str
    conduit_id: str
    length_mm: float
    penetrations: int
    cost: float
    nodes: list[Node]

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "conduit_id": self.conduit_id,
            "length_mm": round(self.length_mm, COORD_ROUND),
            "penetrations": self.penetrations,
            "cost": round(self.cost, COORD_ROUND),
            "nodes": [[round(x, COORD_ROUND), round(y, COORD_ROUND)] for x, y in self.nodes],
        }


@dataclass
class RoutingResult:
    home_runs: list[HomeRun]
    drops: list[dict[str, Any]]  # {"id", "device_id", "path"}
    trunks: list[dict[str, Any]]  # {"id", "path"}
    items: list[ReviewItem]
    counters: dict[str, int] = field(default_factory=dict)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, i: int) -> int:
        while self.parent.setdefault(i, i) != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _rated(wall: dict[str, Any]) -> bool:
    return wall_fire_rating_hr(wall) >= 1.0 or bool(wall.get("is_demising"))


def stack_squares(stacks: list[tuple[str, float]], walls: dict[str, dict[str, Any]]) -> list:
    squares = []
    for wall_id, offset in stacks:
        sx, sy = pt_on_wall(walls[wall_id], offset)
        squares.append(
            box(
                sx - E4_STACK_EXCLUSION_MM,
                sy - E4_STACK_EXCLUSION_MM,
                sx + E4_STACK_EXCLUSION_MM,
                sy + E4_STACK_EXCLUSION_MM,
            )
        )
    return squares


def build_graph(
    inputs: MepInputs,
    stacks: list[tuple[str, float]],
    devices: list[Device],
    panel_foot: Node,
    panel_wall_id: str,
    forbidden: list[Any] | None = None,
) -> Graph:
    walls = inputs.walls
    squares = stack_squares(stacks, walls)
    obstacles = list(forbidden or [])
    # ---- candidate points per wall
    raw: list[tuple[Node, str]] = []
    lines = {wid: LineString([tuple(w["start"]), tuple(w["end"])]) for wid, w in walls.items()}
    ordered = sorted(walls)
    for wid in ordered:
        w = walls[wid]
        raw.append((tuple(w["start"]), wid))  # type: ignore[arg-type]
        raw.append((tuple(w["end"]), wid))  # type: ignore[arg-type]
        for other in ordered:
            if other <= wid:
                continue
            inter = lines[wid].intersection(lines[other])
            if inter.is_empty:
                continue
            pts = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
            for p in pts:
                if p.geom_type == "Point":
                    raw.append(((p.x, p.y), wid))
                    raw.append(((p.x, p.y), other))
        for wall_id, offset in stacks:
            if wall_id == wid:
                for t in (offset - E4_STACK_EXCLUSION_MM, offset + E4_STACK_EXCLUSION_MM):
                    if 0.0 <= t <= wall_len(w):
                        raw.append((pt_on_wall(w, t), wid))
    for d in devices:
        raw.append((pt_on_wall(walls[d.host_wall_id], d.offset), d.host_wall_id))
    raw.append((panel_foot, panel_wall_id))
    # ---- canonicalize within GRAPH_NODE_TOL_MM (union-find on the point list)
    uf = _UnionFind()
    for i in range(len(raw)):
        for j in range(i + 1, len(raw)):
            if math.dist(raw[i][0], raw[j][0]) <= GRAPH_NODE_TOL_MM:
                uf.union(i, j)
    rep: dict[int, Node] = {}
    node_walls: dict[Node, set[str]] = {}
    canon: list[Node | None] = [None] * len(raw)
    for i, (_pt, wid) in enumerate(raw):
        root = uf.find(i)
        if root not in rep:
            rep[root] = (round(raw[root][0][0], COORD_ROUND), round(raw[root][0][1], COORD_ROUND))
        canon[i] = rep[root]
        node_walls.setdefault(rep[root], set()).add(wid)
    nodes = sorted(set(rep.values()))
    # ---- edges: consecutive nodes along each wall, unless the open segment crosses a
    #      stack square or a forbidden obstacle
    edges: dict[Node, list[tuple[Node, str, float]]] = {n: [] for n in nodes}
    for wid in ordered:
        w = walls[wid]
        on_wall = sorted({n for n in nodes if wid in node_walls[n]}, key=lambda n: offset_of(n, w))
        for a, b in zip(on_wall, on_wall[1:], strict=False):
            seg = LineString([a, b])
            if any(seg.intersection(sq).length > 1e-6 for sq in squares):
                continue
            if any(seg.intersection(ob).length > 1e-6 for ob in obstacles):
                continue
            length = math.dist(a, b)
            if length <= 1e-9:
                continue
            edges[a].append((b, wid, length))
            edges[b].append((a, wid, length))
    for n in nodes:
        edges[n].sort(key=lambda e: (e[1], e[0]))
    # ---- interior-of-rated-wall membership
    interior_of: dict[Node, set[str]] = {n: set() for n in nodes}
    for wid in ordered:
        w = walls[wid]
        if not _rated(w):
            continue
        length = wall_len(w)
        for n in nodes:
            if wid not in node_walls[n]:
                continue
            t = offset_of(n, w)
            if 1.0 < t < length - 1.0:
                interior_of[n].add(wid)
    return Graph(nodes, edges, interior_of, node_walls)


def dijkstra(
    graph: Graph, source: Node, source_wall: str, deadline_check: DeadlineCheck = None
) -> tuple[dict[tuple[Node, str | None], float], dict[tuple[Node, str | None], Any], int]:
    """Single-source over states (node, arriving_wall). Relaxing u->v along wall C
    from state (u, A) costs len + 4000 per rated wall B with u strictly inside B and
    A != B (pass-through or turn-in; arriving along B is free). Ties resolve on
    (cost, node, wall) — deterministic."""
    start = (source, source_wall)
    dist: dict[tuple[Node, str | None], float] = {start: 0.0}
    prev: dict[tuple[Node, str | None], Any] = {start: None}
    heap: list[tuple[float, Node, str, Node, str | None]] = [
        (0.0, source, source_wall, source, source_wall)
    ]
    states = 0
    cap = len(graph.nodes) * (len({w for ws in graph.node_walls.values() for w in ws}) + 1)
    done: set[tuple[Node, str | None]] = set()
    while heap:
        cost, node, wall, _n, _w = heapq.heappop(heap)
        state = (node, wall)
        if state in done:
            continue
        done.add(state)
        states += 1
        assert states <= cap, "E-4 Dijkstra state bound violated"
        if deadline_check and states % 64 == 0:
            deadline_check()
        for other, via, length in graph.edges[node]:
            pen = sum(1 for b in graph.interior_of[node] if b != wall)
            new_cost = cost + length + E4_PENETRATION_PENALTY_MM * pen
            nstate = (other, via)
            if new_cost < dist.get(nstate, math.inf) - 1e-9:
                dist[nstate] = new_cost
                prev[nstate] = (state, pen)
                heapq.heappush(heap, (new_cost, other, via, node, wall))
    return dist, prev, states


def route_home_runs(
    inputs: MepInputs,
    devices: list[Device],
    stacks: list[tuple[str, float]],
    deadline_check: DeadlineCheck = None,
    forbidden: list[Any] | None = None,
    next_conduit: int = 1,
) -> RoutingResult:
    items: list[ReviewItem] = []
    if inputs.panel_node is None or inputs.panel_wall_id is None:
        empty = {"graph_nodes": 0, "graph_edges": 0, "dijkstra_states": 0}
        return RoutingResult([], [], [], items, empty)
    graph = build_graph(inputs, stacks, devices, inputs.panel_node, inputs.panel_wall_id, forbidden)
    source = min(graph.nodes, key=lambda n: math.dist(n, inputs.panel_node))  # type: ignore[arg-type]
    dist, prev, states = dijkstra(graph, source, inputs.panel_wall_id, deadline_check)
    home_runs: list[HomeRun] = []
    drops: list[dict[str, Any]] = []
    tree_edges: set[tuple[Node, Node]] = set()
    for d in devices:
        foot = pt_on_wall(inputs.walls[d.host_wall_id], d.offset)
        node = min(graph.nodes, key=lambda n: math.dist(n, foot))
        candidates = sorted(
            ((c, s) for s, c in dist.items() if s[0] == node),
            key=lambda cs: (round(cs[0], 6), cs[1][1] or ""),
        )
        if not candidates:
            items.append(
                ReviewItem(
                    "device_unroutable",
                    "info",
                    [d.id],
                    f"{d.id}: no wall path from the panel (stack exclusion or isolated wall)",
                )
            )
            continue
        cost, state = candidates[0]
        path: list[Node] = []
        penetrations = 0
        cur: Any = state
        while cur is not None:
            path.append(cur[0])
            link = prev.get(cur)
            if link is None:
                break
            cur, pen = link
            penetrations += pen
        path.reverse()  # panel -> device
        length = sum(math.dist(a, b) for a, b in zip(path, path[1:], strict=False))
        conduit_id = f"Q-{next_conduit:03d}"
        next_conduit += 1
        home_runs.append(HomeRun(d.id, conduit_id, length, penetrations, cost, path))
        drops.append(
            {
                "id": conduit_id,
                "device_id": d.id,
                "path": [
                    [round(node[0], COORD_ROUND), round(node[1], COORD_ROUND), d.height_afl],
                    [round(node[0], COORD_ROUND), round(node[1], COORD_ROUND), E4_CONDUIT_Z_MM],
                ],
            }
        )
        for a, b in zip(path, path[1:], strict=False):
            tree_edges.add((a, b) if a <= b else (b, a))
    # ---- raceway tree trunks: maximal chains between nodes of degree != 2
    trunks: list[dict[str, Any]] = []
    adjacency: dict[Node, list[Node]] = {}
    for a, b in sorted(tree_edges):
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    for n in adjacency:
        adjacency[n].sort()
    endpoints = sorted(n for n, nb in adjacency.items() if len(nb) != 2 or n == source)
    visited: set[tuple[Node, Node]] = set()
    junctions = sum(1 for n, nb in adjacency.items() if len(nb) >= 3)
    for start in endpoints:
        for nxt in adjacency[start]:
            if (start, nxt) in visited:
                continue
            chain = [start, nxt]
            visited.add((start, nxt))
            visited.add((nxt, start))
            while len(adjacency[chain[-1]]) == 2 and chain[-1] != source:
                a, b = adjacency[chain[-1]]
                following = b if a == chain[-2] else a
                if (chain[-1], following) in visited:
                    break
                visited.add((chain[-1], following))
                visited.add((following, chain[-1]))
                chain.append(following)
            pts3 = [(x, y, E4_CONDUIT_Z_MM) for x, y in chain]
            pieces, splits = split_unsupported(pts3)
            if splits:
                junctions += splits
            for piece in pieces:
                for k in range(0, max(1, len(piece) - 1), E4_MAX_PATH_POINTS - 1):
                    chunk = piece[k : k + E4_MAX_PATH_POINTS]
                    if len(chunk) < 2:
                        continue
                    if len(piece) > E4_MAX_PATH_POINTS:
                        items.append(
                            ReviewItem(
                                "conduit_path_too_long",
                                "info",
                                [f"Q-{next_conduit:03d}"],
                                f"raceway chain with {len(piece)} points split at "
                                f"{E4_MAX_PATH_POINTS}",
                            )
                        )
                    trunks.append(
                        {
                            "id": f"Q-{next_conduit:03d}",
                            "path": [
                                [round(x, COORD_ROUND), round(y, COORD_ROUND), z]
                                for x, y, z in chunk
                            ],
                        }
                    )
                    next_conduit += 1
    if junctions:
        items.append(
            ReviewItem(
                "conduit_fittings_manual",
                "info",
                [inputs.panel_wall_id],
                f"{junctions} raceway junction(s)/odd bend(s) to fit manually (v1: elbows only)",
            )
        )
    counters = {**graph.counts(), "dijkstra_states": states}
    return RoutingResult(home_runs, drops, trunks, items, counters)
