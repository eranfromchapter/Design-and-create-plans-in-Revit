"""Part G placement primitives + the pinned deterministic orders. Production
placement code carries no RNG and no clock — asserted against the source."""

from __future__ import annotations

import ast
from pathlib import Path

from helpers import door, make_layout, room, wall
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


def test_spiral_positions_geometry_pinned():
    from layout_compiler.interior import spiral_positions

    positions = spiral_positions((1000.0, 2000.0))
    assert len(positions) == 81  # anchor + 10 rings x 8 angles
    assert positions[0] == (1000.0, 2000.0)
    assert len(set(positions)) == 81  # all distinct
    import math as m

    for ring in range(1, 11):
        for k in range(8):
            x, y = positions[1 + (ring - 1) * 8 + k]  # ring-major order
            assert m.isclose(m.hypot(x - 1000.0, y - 2000.0), ring * 50.0, abs_tol=1e-9)
        # first angle of each ring points along +x
        assert m.isclose(positions[1 + (ring - 1) * 8][0], 1000.0 + ring * 50.0, abs_tol=1e-9)


def test_spiral_places_at_a_ring_beyond_the_anchor():
    """Two identical free-standing nightstands proposed at the same center:
    the second must walk the spiral to the first ring where the rects merely
    touch (450mm out, angle 0) — pinning ring geometry beyond candidate #1."""
    a = nightstand(1, [2000.0, 1500.0], wall_seeking=False)
    b = nightstand(2, [2000.0, 1500.0], wall_seeking=False)
    outcome = legalize_furniture([a, b], layout_4x3())
    assert outcome.unplaced == []
    items = {i["id"]: i for e in outcome.furniture for i in e["items"]}
    assert items["F-001"]["center"] == [2000.0, 1500.0]
    assert items["F-002"]["center"] == [2450.0, 1500.0]  # ring 9 (450mm), angle 0: touching
    diag = next(d for d in outcome.diagnostics["items"] if d["item_id"] == "F-002")
    # anchor (4 rotations) + rings 1..8 all overlap (64 positions x 4) -> 261st candidate
    assert diag["spiral_tried"] == 261


def test_out_of_room_proposal_is_review_not_relocated():
    """Part G pin: the spiral runs around the PROPOSED center, never a clamped
    substitute — an out-of-room hint exhausts the bounded search and lands in
    REVIEW rather than being silently moved."""
    table = {
        "id": "F-001",
        "room_id": "R-001",
        "kind": "table",
        "revit_family": "CHPT_DiningTable_PLACEHOLDER",
        "revit_type": "Dining_900x1800_PLACEHOLDER",
        "center": [9000.0, 9000.0],  # nowhere near the 4000x3000 room
        "rotation_deg": 0.0,
        "footprint": [900.0, 1800.0],
    }
    outcome = legalize_furniture([table], layout_4x3())
    assert [u["item"]["id"] for u in outcome.unplaced] == ["F-001"]
    assert outcome.diagnostics["items"][0]["spiral_tried"] == 324  # full bounded exhaustion


def test_plumbing_closure_overwrites_fixture_units_and_wet_hookups():
    wc = {
        "id": "F-001",
        "room_id": "R-001",
        "kind": "wc",
        "revit_family": "CHPT_WC_PLACEHOLDER",
        "revit_type": "WC_400x700_PLACEHOLDER",
        "center": [3200.0, 400.0],
        "rotation_deg": 0.0,
        "footprint": [400.0, 700.0],
        "fixture_units": 99.0,  # lie
        "hookups": ["gas"],  # wet hookups dropped entirely
    }
    outcome = legalize_furniture([wc], layout_4x3())
    item = outcome.furniture[0]["items"][0]
    assert item["fixture_units"] == 4.0  # catalogs/plumbing.json owns this
    # plumbing hookups restored; the proposed dry extra stays additive
    assert item["hookups"] == ["sanitary", "supply_c", "vent", "gas"]


def test_deadline_check_interrupts_the_solver():
    calls = {"n": 0}

    def tripwire() -> None:
        calls["n"] += 1
        if calls["n"] > 2:
            raise RuntimeError("deadline")

    import pytest

    with pytest.raises(RuntimeError, match="deadline"):
        legalize_furniture(
            [nightstand(1, [3500.0, 400.0]), nightstand(2, [500.0, 400.0])],
            layout_4x3(),
            deadline_check=tripwire,
        )


def test_rotated_room_placement_is_exact():
    """A room rigidly rotated 30°: the stamped rotation equals the wall angle
    and the center equals the rotated back-to-wall point — kills any axis-only
    degeneracy in the trig (mutation-hardening)."""
    import math as m

    def rot(x: float, y: float) -> list[float]:
        c, s = m.cos(m.radians(30.0)), m.sin(m.radians(30.0))
        return [x * c - y * s, x * s + y * c]

    corners = [rot(0, 0), rot(4000, 0), rot(4000, 3000), rot(0, 3000)]
    walls = [
        wall(1, corners[0], corners[1]),
        wall(2, corners[1], corners[2]),
        wall(3, corners[2], corners[3]),
        wall(4, corners[3], corners[0]),
    ]
    layout = make_layout(
        walls=walls,
        doors=[door(1, "W-001", 2000)],
        rooms=[room(1, corners, [w["id"] for w in walls])],
    )
    outcome = legalize_furniture([nightstand(1, rot(3500, 400))], layout)
    assert outcome.unplaced == []
    item = outcome.furniture[0]["items"][0]
    assert item["rotation_deg"] == 30.0  # the wall angle, not an axis snap
    expected = rot(3500, 271)  # foot (3500,0) + n̂·(46+225) in room frame
    assert item["center"] == [round(expected[0], 1), round(expected[1], 1)]


def test_production_placer_has_no_rng_and_no_clock():
    src = Path("src/layout_compiler/interior.py").read_text()
    tree = ast.parse(src)
    imported = {
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names
    } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "random" not in imported and "time" not in imported and "datetime" not in imported


def test_free_standing_item_never_sinks_into_a_wall_half_thickness():
    """Proposed centre 240mm from a 92mm wall: the 450 footprint (15..465) is
    inside the CENTERLINE polygon but 31mm inside the wall slab (face at 46) —
    the anchor must be rejected and the spiral must land the item with its
    back at or beyond the inner face."""
    layout = layout_4x3()
    proposal = {**nightstand(1, [240.0, 1500.0]), "wall_seeking": False}
    outcome = legalize_furniture([proposal], layout)
    (item,) = outcome.furniture[0]["items"]
    assert item["center"][0] - 225.0 >= 46.0 - 0.1
    assert outcome.diagnostics["items"][0]["spiral_tried"] > 1  # the anchor itself failed


def test_preplaced_items_seed_the_predicates_and_stay_out_of_the_output():
    """Phase 6 merge-gate seam: a re-legalized single item must not land on furniture
    that is already placed; preplaced items are inputs, never outputs."""
    layout = layout_4x3()
    alone = legalize_furniture([nightstand(1, [3500.0, 400.0])], layout)
    spot = alone.furniture[0]["items"][0]
    preplaced = [{**spot, "room_id": "R-001"}]
    outcome = legalize_furniture([nightstand(2, [3500.0, 400.0])], layout, preplaced=preplaced)
    assert outcome.unplaced == []
    [item] = outcome.furniture[0]["items"]
    assert item["id"] == "F-002" and item["center"] != spot["center"]
    from layout_compiler.geometry import furniture_rect

    assert furniture_rect(item).intersection(furniture_rect(spot)).area == 0
    assert [d["item_id"] for d in outcome.diagnostics["items"]] == ["F-002"]


def test_obstacles_exclude_candidate_footprints():
    layout = layout_4x3()
    free = legalize_furniture([nightstand(1, [3500.0, 400.0])], layout)
    spot = free.furniture[0]["items"][0]["center"]
    blocker = Polygon([(3000, 0), (4000, 0), (4000, 600), (3000, 600)])  # covers the spot
    outcome = legalize_furniture([nightstand(1, [3500.0, 400.0])], layout, obstacles=[blocker])
    assert outcome.unplaced == []
    [item] = outcome.furniture[0]["items"]
    assert item["center"] != spot
    from layout_compiler.geometry import furniture_rect

    assert furniture_rect(item).intersection(blocker).area == 0
    # the defaults are the Phase 5 placer verbatim
    assert legalize_furniture([nightstand(1, [3500.0, 400.0])], layout) == free
