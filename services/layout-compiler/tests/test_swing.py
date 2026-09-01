"""Door-swing conventions (Phase 5 v1 pins), conformance-tested for all four
swing x flip combinations against the module docstring's worked example, plus
the single-room arc assignment on the real golden 4BR plan."""

from __future__ import annotations

import math

from helpers import make_layout
from shapely.geometry import Polygon

from layout_compiler.golden_4br import emission
from layout_compiler.swing import door_swing_arc, hinge_point, room_swing_arcs
from layout_compiler.validator import validate_layout

WALL = {
    "id": "W-001",
    "start": [0.0, 0.0],
    "end": [3000.0, 0.0],
    "revit_type": "CHPT_Partition_92mm_PLACEHOLDER",
}


def door(swing: str, flip: bool) -> dict:
    return {
        "id": "D-001",
        "host_wall_id": "W-001",
        "offset": 1500.0,
        "width": 900.0,
        "height": 2040.0,
        "revit_type": "CHPT_Door_Single_PLACEHOLDER",
        "swing": swing,
        "flip_facing": flip,
    }


def test_all_swing_flip_combos():
    cases = {
        ("L", False): ((1050.0, 0.0), (1050.0, 0.0, 1950.0, 900.0)),
        ("R", False): ((1950.0, 0.0), (1050.0, 0.0, 1950.0, 900.0)),
        ("L", True): ((1050.0, 0.0), (1050.0, -900.0, 1950.0, 0.0)),
        ("R", True): ((1950.0, 0.0), (1050.0, -900.0, 1950.0, 0.0)),
    }
    for (swing, flip), (hinge, bbox) in cases.items():
        d = door(swing, flip)
        assert hinge_point(d, WALL) == hinge, (swing, flip)
        arc = door_swing_arc(d, WALL)
        assert arc is not None
        minx, miny, maxx, maxy = arc.bounds
        assert [round(v, 6) for v in (minx, miny, maxx, maxy)] == list(bbox), (swing, flip)
        # a 16-segment quarter disc holds ~99.7% of the true quarter-circle area
        assert math.isclose(arc.area, math.pi * 900.0**2 / 4, rel_tol=0.01)


def test_swing_defaults_to_left_hinge():
    bare = {k: v for k, v in door("L", False).items() if k not in ("swing", "flip_facing")}
    assert hinge_point(bare, WALL) == (1050.0, 0.0)


def test_pocket_doors_emit_no_arc():
    pocket = {**door("L", False), "revit_type": "CHPT_Door_Pocket_PLACEHOLDER"}
    assert door_swing_arc(pocket, WALL) is None


def test_single_room_assignment_on_the_golden_plan():
    """D-011 sweeps into the LAUNDRY (never the kitchen), D-009 into Bath 1,
    D-001 (entry, on the north party wall) into no room at all."""
    layout = emission()
    walls = {w["id"]: w for w in layout["walls"]}
    rooms = {r["id"]: r for r in layout["rooms"]}

    def arc_door_ids(room_id: str) -> set[str]:
        room = rooms[room_id]
        polygon = Polygon(room["boundary"])
        return {d for d, _ in room_swing_arcs(room, polygon, layout["doors"], walls)}

    assert "D-011" in arc_door_ids("R-011")  # laundry gets the swing
    assert "D-011" not in arc_door_ids("R-009")  # kitchen does not
    assert "D-009" in arc_door_ids("R-003")  # bath 1
    assert "D-009" not in arc_door_ids("R-002")  # not the bedroom
    assert all("D-001" not in arc_door_ids(rid) for rid in rooms)  # entry sweeps outward
    # pocket doors constrain nothing
    assert all("D-006" not in arc_door_ids(rid) for rid in rooms)
    assert all("D-008" not in arc_door_ids(rid) for rid in rooms)


def test_furniture_in_a_swing_arc_is_rejected_by_the_validator():
    # D-001 in make_layout: host W-001 (0,0)->(4000,0), offset 2000, width 915,
    # swing L, flip falsy -> hinge (1542.5, 0), sweeps into the room (y > 0)
    inside_arc = {
        "id": "F-001",
        "kind": "table",
        "revit_family": "CHPT_Nightstand_PLACEHOLDER",
        "revit_type": "Nightstand_450x450_PLACEHOLDER",
        "center": [1900.0, 400.0],
        "rotation_deg": 0.0,
        "footprint": [450.0, 450.0],
    }
    layout = make_layout(furniture=[{"room_id": "R-001", "items": [inside_arc]}])
    errors = validate_layout(layout)
    assert any("intersects door D-001 swing arc" in e for e in errors)

    clear = {**inside_arc, "center": [3200.0, 400.0]}  # same wall, outside the arc
    layout = make_layout(furniture=[{"room_id": "R-001", "items": [clear]}])
    assert validate_layout(layout) == []
