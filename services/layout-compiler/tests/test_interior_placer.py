"""Part G placement primitives + the pinned deterministic orders. Production
placement code carries no RNG and no clock — asserted against the source."""

from __future__ import annotations

import ast
from pathlib import Path

from helpers import make_layout
from shapely.geometry import Polygon

from layout_compiler.interior import (
    MAX_CANDIDATES_PER_WALL,
    SLIDE_SEQUENCE_MM,
    SPIRAL_CAP,
    T_FINISH_MM,
    _normalize_rotation,
    aabb_of,
    aabbs_overlap,
    back_to_wall_center,
    legalize_furniture,
    project_to_wall,
    room_facing_normal,
)

ROOM_POLY = Polygon([(0, 0), (4000, 0), (4000, 3000), (0, 3000)])
SOUTH = {"id": "W-001", "start": [0.0, 0.0], "end": [4000.0, 0.0]}


def nightstand(i: int, center: list[float], **over) -> dict:
    return {
        "id": f"F-{i:03d}",
        "room_id": "R-001",
        "kind": "table",
        "revit_family": "CHPT_Nightstand_PLACEHOLDER",
        "revit_type": "Nightstand_450x450_PLACEHOLDER",
        "center": center,
        "rotation_deg": 0.0,
        "footprint": [450.0, 450.0],
        **over,
    }


def test_projection_clamps_to_the_segment():
    assert project_to_wall((2000.0, 500.0), SOUTH) == (0.5, (2000.0, 0.0))
    assert project_to_wall((-500.0, 100.0), SOUTH) == (0.0, (0.0, 0.0))
    assert project_to_wall((9000.0, 100.0), SOUTH) == (1.0, (4000.0, 0.0))


def test_room_facing_normal_points_into_the_room():
    assert room_facing_normal(SOUTH, (2000.0, 0.0), ROOM_POLY) == (0.0, 1.0)
    north = {"id": "W-003", "start": [4000.0, 3000.0], "end": [0.0, 3000.0]}
    assert room_facing_normal(north, (2000.0, 3000.0), ROOM_POLY) == (0.0, -1.0)
    faraway = {"id": "W-009", "start": [0.0, 9000.0], "end": [4000.0, 9000.0]}
    assert room_facing_normal(faraway, (2000.0, 9000.0), ROOM_POLY) is None


def test_back_to_wall_offset_formula():
    # t_wall/2 + t_finish + d_item/2 with the pinned t_finish = 0
    assert T_FINISH_MM == 0.0
    for t_wall in (92.0, 152.0, 250.0, 300.0):
        cx, cy = back_to_wall_center((2000.0, 0.0), (0.0, 1.0), t_wall, 700.0)
        assert (cx, cy) == (2000.0, t_wall / 2 + 350.0)


def test_slide_sequence_pinned():
    assert len(SLIDE_SEQUENCE_MM) == 81
    assert SLIDE_SEQUENCE_MM[:5] == (0.0, 50.0, -50.0, 100.0, -100.0)
    assert SLIDE_SEQUENCE_MM[-2:] == (2000.0, -2000.0)
    assert MAX_CANDIDATES_PER_WALL == 162
    assert SPIRAL_CAP == 324


def test_rotation_normalization():
    assert _normalize_rotation(270.0 + 90.0) == 0.0  # the 360.0 emission bug
    assert _normalize_rotation(-90.0) == 270.0
    assert _normalize_rotation(359.96) == 0.0  # rounds to 360.0 -> normalized


def test_aabb_matches_the_sim_formula():
    assert aabb_of((1000.0, 1000.0), 0.0, (2000.0, 600.0)) == (0.0, 700.0, 2000.0, 1300.0)
    minx, miny, maxx, maxy = aabb_of((0.0, 0.0), 90.0, (2000.0, 600.0))
    assert (round(minx), round(miny), round(maxx), round(maxy)) == (-300, -1000, 300, 1000)
    assert not aabbs_overlap((0, 0, 100, 100), (100, 0, 200, 100))  # touching legal
    assert aabbs_overlap((0, 0, 101, 100), (100, 0, 200, 100))


def layout_4x3() -> dict:
    return make_layout()


def test_wall_seeking_places_back_to_nearest_wall():
    layout = layout_4x3()
    outcome = legalize_furniture([nightstand(1, [3500.0, 400.0])], layout)
    assert outcome.unplaced == []
    item = outcome.furniture[0]["items"][0]
    # nearest wall is the south wall (92mm partition): back-to-wall y = 46 + 225
    assert item["center"][1] == 271.0
    assert item["rotation_deg"] == 0.0
    assert item["clearance_front"] == 0.0  # stamped from the catalog
    assert item["wall_seeking"] is True
    diag = outcome.diagnostics["items"][0]
    assert diag["placed"] and diag["method"] == "wall" and diag["wall_id"] == "W-001"


def test_free_standing_spiral_places_at_the_proposal():
    layout = layout_4x3()
    table = {
        "id": "F-001",
        "room_id": "R-001",
        "kind": "table",
        "revit_family": "CHPT_DiningTable_PLACEHOLDER",
        "revit_type": "Dining_900x1800_PLACEHOLDER",
        "center": [2000.0, 1800.0],
        "rotation_deg": 0.0,
        "footprint": [900.0, 1800.0],
    }
    outcome = legalize_furniture([table], layout)
    assert outcome.unplaced == []
    item = outcome.furniture[0]["items"][0]
    assert item["center"] == [2000.0, 1800.0]  # ring 0 accepted...
    # ...but only at +90: upright, the table splits the eroded circulation into
    # two arms and D-001's threshold becomes unreachable — the predicate works
    assert item["rotation_deg"] == 90.0
    assert item["wall_seeking"] is False  # catalog default for the dining table
    diag = outcome.diagnostics["items"][0]
    assert diag["method"] == "spiral" and diag["spiral_tried"] == 2


def test_footprint_and_clearance_come_from_the_catalog():
    lying = nightstand(1, [2000.0, 1500.0], footprint=[5.0, 5.0], clearance_front=9999.0)
    outcome = legalize_furniture([lying], layout_4x3())
    item = outcome.furniture[0]["items"][0]
    assert item["footprint"] == [450.0, 450.0]
    assert item["clearance_front"] == 0.0


def test_legalize_is_deterministic_and_order_insensitive():
    proposals = [
        nightstand(2, [3500.0, 400.0]),
        nightstand(1, [500.0, 2500.0]),
        {
            "id": "F-003",
            "room_id": "R-001",
            "kind": "sofa",
            "revit_family": "CHPT_Sofa_PLACEHOLDER",
            "revit_type": "Sofa_2100x900_PLACEHOLDER",
            "center": [2000.0, 2550.0],
            "rotation_deg": 0.0,
            "footprint": [2100.0, 900.0],
        },
    ]
    layout = layout_4x3()
    first = legalize_furniture(proposals, layout)
    second = legalize_furniture(proposals, layout)
    shuffled = legalize_furniture(list(reversed(proposals)), layout)
    assert first.furniture == second.furniture == shuffled.furniture
    assert first.unplaced == second.unplaced == shuffled.unplaced


def test_production_placer_has_no_rng_and_no_clock():
    src = Path("src/layout_compiler/interior.py").read_text()
    tree = ast.parse(src)
    imported = {
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "random" not in imported and "time" not in imported and "datetime" not in imported
