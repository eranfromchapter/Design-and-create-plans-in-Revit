"""PLAN.md Phase 5 acceptance bullet 4 (oversized -> REVIEW, never force-placed)
plus the adversarial arc case: a candidate that passes every other predicate but
sweeps a door is rejected."""

from __future__ import annotations

from helpers import make_layout

from layout_compiler.interior import legalize_furniture


def test_oversized_item_review_not_forced():
    whale = {
        "id": "F-001",
        "room_id": "R-001",
        "kind": "bed",
        "revit_family": "CHPT_Bed_PLACEHOLDER",
        "revit_type": "Queen_1524x2032_PLACEHOLDER",
        "center": [2000.0, 1500.0],
        "rotation_deg": 0.0,
        "footprint": [1524.0, 2032.0],
    }
    # a 2000x1500 'other' room cannot hold a queen bed in any orientation
    from helpers import door, room, wall

    walls = [
        wall(1, [0, 0], [2000, 0]),
        wall(2, [2000, 0], [2000, 1500]),
        wall(3, [2000, 1500], [0, 1500]),
        wall(4, [0, 1500], [0, 0]),
    ]
    layout = make_layout(
        walls=walls,
        doors=[door(1, "W-001", 1000, width=762)],
        rooms=[
            room(
                1,
                [[0, 0], [2000, 0], [2000, 1500], [0, 1500]],
                [w["id"] for w in walls],
                program="other",
            )
        ],
    )
    outcome = legalize_furniture([whale], layout)
    assert outcome.furniture == []  # never force-placed
    assert [u["item"]["id"] for u in outcome.unplaced] == ["F-001"]
    assert outcome.unplaced[0]["reason"]
    diag = outcome.diagnostics["items"][0]
    assert diag["placed"] is False and diag["reason"]


def test_adversarial_swing_arc_is_load_bearing():
    """In make_layout, D-001 (W-001, offset 2000, width 915, swing L) sweeps
    y>0 from hinge (1542.5, 0). A nightstand proposed dead inside that arc
    passes room/overlap/AABB/circulation — only the arc predicate can reject
    the first candidates, pushing the accepted slide outside the arc."""
    inside_arc = {
        "id": "F-001",
        "room_id": "R-001",
        "kind": "table",
        "revit_family": "CHPT_Nightstand_PLACEHOLDER",
        "revit_type": "Nightstand_450x450_PLACEHOLDER",
        "center": [1900.0, 300.0],
        "rotation_deg": 0.0,
        "footprint": [450.0, 450.0],
    }
    outcome = legalize_furniture([inside_arc], make_layout())
    assert outcome.unplaced == []
    item = outcome.furniture[0]["items"][0]
    # placed against the south wall but slid clear of the swing arc:
    # arc spans x 1542.5..2457.5, so the accepted center is outside that band
    assert item["center"][1] == 271.0
    cx = item["center"][0]
    assert cx + 225.0 <= 1542.5 or cx - 225.0 >= 2457.5
    assert outcome.diagnostics["items"][0]["candidates_tried"] > 1  # earlier slides rejected
