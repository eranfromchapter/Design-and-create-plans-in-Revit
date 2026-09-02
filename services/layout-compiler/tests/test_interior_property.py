"""PLAN.md Phase 5 acceptance bullets 1-2 as a property test: 200 seeded rooms
(seeded PRNG — deterministic run to run), random catalog furniture of BOTH
classes; every placed pair must be positive-area disjoint AND sim-AABB
disjoint, no placed item may touch a swing arc, and the assembled furnished
layout must pass the full validator (the independent oracle).

Odd seeds rotate the whole case rigidly by a seeded non-axis angle (walls,
boundary, proposal centers together) — the invariants are frame-independent,
so an axis-aligned-only corpus would let trig chirality/rounding bugs
through (adversarial review finding)."""

from __future__ import annotations

import math
import random
from typing import Any

import pytest
from helpers import PROJECT_ID
from shapely.geometry import Polygon

from layout_compiler.geometry import OVERLAP_EPS_MM2, furniture_rect
from layout_compiler.interior import aabb_of, aabbs_overlap, legalize_furniture
from layout_compiler.swing import room_swing_arcs
from layout_compiler.validator import validate_layout

# rigid-rotation corpus for odd seeds: deliberately non-axis angles (45 is the
# AABB worst case; 30/22.5/11.25 exercise irrational trig)
ROTATION_CORPUS = [11.25, 22.5, 30.0, 45.0]


def rot(pt: list[float] | tuple[float, float], deg: float) -> list[float]:
    rad = math.radians(deg)
    x, y = pt
    return [x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad)]


# (family, type, kind, wall_seeking pool entry) — real catalog vocabulary only
POOL: list[tuple[str, str, str]] = [
    ("CHPT_Nightstand_PLACEHOLDER", "Nightstand_450x450_PLACEHOLDER", "table"),
    ("CHPT_Desk_PLACEHOLDER", "Desk_1200x600_PLACEHOLDER", "desk"),
    ("CHPT_Wardrobe_PLACEHOLDER", "Wardrobe_1000x600_PLACEHOLDER", "wardrobe"),
    ("CHPT_Bed_PLACEHOLDER", "Twin_991x1905_PLACEHOLDER", "bed"),
    ("CHPT_Sofa_PLACEHOLDER", "Sofa_2100x900_PLACEHOLDER", "sofa"),
    ("CHPT_DiningTable_PLACEHOLDER", "Dining_900x1800_PLACEHOLDER", "table"),
]


def seeded_case(seed: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rng = random.Random(seed)
    width = rng.randrange(2400, 5201, 50)
    height = rng.randrange(2400, 5201, 50)
    walls = [
        {
            "id": f"W-{i:03d}",
            "start": start,
            "end": end,
            "revit_type": "CHPT_Partition_92mm_PLACEHOLDER",
            "height": 2700.0,
            "source": "generated",
        }
        for i, (start, end) in enumerate(
            [
                ([0.0, 0.0], [float(width), 0.0]),
                ([float(width), 0.0], [float(width), float(height)]),
                ([float(width), float(height)], [0.0, float(height)]),
                ([0.0, float(height)], [0.0, 0.0]),
            ],
            start=1,
        )
    ]
    doors = []
    door_walls = rng.sample(["W-001", "W-002"], k=rng.randint(1, 2))
    for i, wall_id in enumerate(door_walls, start=1):
        length = width if wall_id == "W-001" else height
        offset = rng.randrange(500, length - 500 + 1, 50)
        doors.append(
            {
                "id": f"D-{i:03d}",
                "host_wall_id": wall_id,
                "offset": float(offset),
                "width": 762.0,
                "height": 2040.0,
                "revit_type": "CHPT_Door_Single_PLACEHOLDER",
                "swing": rng.choice(["L", "R"]),
            }
        )
    layout = {
        "meta": {
            "project_id": PROJECT_ID,
            "level": "Level 1",
            "units": "mm",
            "origin": "revit_internal_origin",
            "schema_version": "2.3",
            "brief_version": 1,
            "phase": "new",
        },
        "walls": walls,
        "doors": doors,
        "windows": [],
        "rooms": [
            {
                "id": "R-001",
                "name": f"Seeded {seed}",
                "program": "other",
                "boundary": [
                    [0.0, 0.0],
                    [float(width), 0.0],
                    [float(width), float(height)],
                    [0.0, float(height)],
                ],
                "boundary_wall_ids": [w["id"] for w in walls],
            }
        ],
        "furniture": [],
        "constraints": {"circulation_min": 900},
    }
    proposals = []
    for i in range(rng.randint(1, 4)):
        family, revit_type, kind = rng.choice(POOL)
        proposals.append(
            {
                "id": f"F-{i + 1:03d}",
                "room_id": "R-001",
                "kind": kind,
                "revit_family": family,
                "revit_type": revit_type,
                "center": [
                    float(rng.randrange(200, width - 200, 50)),
                    float(rng.randrange(200, height - 200, 50)),
                ],
                "rotation_deg": 0.0,
                "footprint": [1.0, 1.0],  # overwritten from the catalog, always
            }
        )
    if seed % 2:  # odd seeds: rotate the whole case rigidly off-axis
        angle = rng.choice(ROTATION_CORPUS)
        for wall in layout["walls"]:
            wall["start"] = rot(wall["start"], angle)
            wall["end"] = rot(wall["end"], angle)
        room = layout["rooms"][0]
        room["boundary"] = [rot(pt, angle) for pt in room["boundary"]]
        for proposal in proposals:
            proposal["center"] = rot(proposal["center"], angle)
    return layout, proposals


@pytest.mark.parametrize("seed", range(200))
def test_zero_footprint_overlaps_and_clear_swings_200_seeded_rooms(seed: int):
    layout, proposals = seeded_case(seed)
    outcome = legalize_furniture(proposals, layout)

    placed = [item for entry in outcome.furniture for item in entry["items"]]
    rects = [(item["id"], furniture_rect(item)) for item in placed]
    boxes = [aabb_of(tuple(i["center"]), i["rotation_deg"], i["footprint"]) for i in placed]
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            assert rects[i][1].intersection(rects[j][1]).area <= OVERLAP_EPS_MM2, seed
            assert not aabbs_overlap(boxes[i], boxes[j]), seed

    room = layout["rooms"][0]
    polygon = Polygon(room["boundary"])
    walls_by_id = {w["id"]: w for w in layout["walls"]}
    arcs = room_swing_arcs(room, polygon, layout["doors"], walls_by_id)
    for _item_id, rect in rects:
        for _door_id, arc in arcs:
            assert rect.intersection(arc).area <= OVERLAP_EPS_MM2, seed

    # independent oracle: the assembled furnished layout passes the validator
    furnished = {**layout, "furniture": outcome.furniture}
    assert validate_layout(furnished) == [], (seed, validate_layout(furnished))

    # every item is accounted for exactly once
    assert len(placed) + len(outcome.unplaced) == len(proposals), seed
