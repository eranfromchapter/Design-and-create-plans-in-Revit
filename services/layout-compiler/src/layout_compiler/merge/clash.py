"""Phase A clash sweep (docs/PHASE6_DESIGN.md §4.3): STRtree over prism footprints;
a candidate pair clashes iff not exempt, positive-area footprint overlap
(> OVERLAP_EPS_MM2) AND strict z overlap. Reported as (a = higher priority, b =
lower), sorted; bounded by |prisms|^2; deadline polled per query."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.strtree import STRtree

from layout_compiler.catalogs import clash_prisms
from layout_compiler.geometry import OVERLAP_EPS_MM2
from layout_compiler.mep.inputs import DeadlineCheck
from layout_compiler.merge.prisms import Prism


@dataclass(frozen=True)
class Clash:
    a_id: str
    b_id: str
    a_cls: str
    b_cls: str
    a_priority: int
    b_priority: int
    overlap_area_mm2: float
    z_overlap_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "a_id": self.a_id,
            "b_id": self.b_id,
            "a_cls": self.a_cls,
            "b_cls": self.b_cls,
            "a_priority": self.a_priority,
            "b_priority": self.b_priority,
            "overlap_area_mm2": round(self.overlap_area_mm2, 3),
            "z_overlap_mm": round(self.z_overlap_mm, 3),
        }


def exempt(a: Prism, b: Prism) -> bool:
    """The shared exemption table (catalogs/clash_prisms.json); here
    `pipe_serves_fixture` IS resolvable: a pipe segment is exempt from the fixture it
    drains."""
    for rule in clash_prisms()["exempt_pairs"]:
        if rule["a"] == rule["b"]:
            if not (a.cls == b.cls == rule["a"]):
                continue
        elif {a.cls, b.cls} != {rule["a"], rule["b"]}:
            continue
        when = rule.get("when")
        if when is None:
            return True
        if when == "same_system":
            return a.system is not None and a.system == b.system
        if when == "pipe_serves_fixture":
            pipe, fixture = (a, b) if a.cls == "pipe" else (b, a)
            return fixture.element_id in pipe.serves
    return False


def phase_a(prisms: list[Prism], deadline_check: DeadlineCheck = None) -> list[Clash]:
    if not prisms:
        return []
    tree = STRtree([p.polygon for p in prisms])
    seen: set[tuple[str, str]] = set()
    clashes: list[Clash] = []
    for p in prisms:
        if deadline_check:
            deadline_check()
        for j in tree.query(p.polygon):
            j = int(j)
            q = prisms[j]
            if q.element_id == p.element_id:
                continue
            key = (min(p.element_id, q.element_id), max(p.element_id, q.element_id))
            if key in seen:
                continue
            if exempt(p, q):
                continue
            z_overlap = min(p.z1, q.z1) - max(p.z0, q.z0)
            if z_overlap <= 0:
                continue
            area = p.polygon.intersection(q.polygon).area
            if area <= OVERLAP_EPS_MM2:
                continue
            seen.add(key)
            hi, lo = (p, q) if (p.priority, p.element_id) <= (q.priority, q.element_id) else (q, p)
            clashes.append(
                Clash(
                    hi.element_id,
                    lo.element_id,
                    hi.cls,
                    lo.cls,
                    hi.priority,
                    lo.priority,
                    area,
                    z_overlap,
                )
            )
    clashes.sort(key=lambda c: (c.a_id, c.b_id))
    return clashes
