"""E-3 (Part G): latch side, 150 mm from the jamb, 1220 AFF, in the swept-side room —
all four swing x flip combinations on the pinned worked-example wall — plus the
flagged fallback ladder (latch corner -> hinge side -> unplaceable)."""

from __future__ import annotations

import pytest
from helpers import door, room, wall
from mep_helpers import assemble, commit0_for, two_rooms_shared_wall

from layout_compiler.mep.electrical import plan_electrical
from layout_compiler.mep.inputs import resolve_inputs

CONF = {"panel": [50.0, 1500.0], "slab_to_slab_mm": 3000.0}


def switches(layout):
    inputs = resolve_inputs(layout, commit0_for(layout), CONF)
    result = plan_electrical(inputs)
    return {d.door_id: d for d in result.devices if d.rule == "E-3"}, result


@pytest.mark.parametrize(
    ("swing", "flip", "expected_offset", "expected_room"),
    [
        ("L", False, 2100.0, "R-001"),  # hinge 1050, latch 1950 -> +150, sweeps into y > 0
        ("R", False, 900.0, "R-001"),  # hinge 1950, latch 1050 -> -150
        ("L", True, 2100.0, "R-002"),  # flip: sweeps into y < 0 -> the south room
        ("R", True, 900.0, "R-002"),
    ],
)
def test_e3_latch_side_all_conventions(swing, flip, expected_offset, expected_room):
    spec = {"offset": 1500.0, "width": 900.0, "swing": swing}
    if flip:
        spec["flip_facing"] = True
    by_door, _r = switches(two_rooms_shared_wall(door_spec=spec))
    sw = by_door["D-001"]
    assert (sw.host_wall_id, sw.offset, sw.height_afl, sw.kind) == (
        "W-001",
        expected_offset,
        1220.0,
        "switch",
    )
    assert sw.room_id == expected_room
    assert sw.face == ("left" if expected_room == "R-001" else "right")


def narrow_room(door_offset: float, door_width: float, block_adjacent: bool = False):
    """A 1000 x 2400 room whose door sits on the 1000 mm wall W-001 (the D-013 geometry)."""
    walls = [
        wall(1, [0, 0], [1000, 0]),
        wall(2, [1000, 0], [1000, 2400]),
        wall(3, [1000, 2400], [0, 2400]),
        wall(4, [0, 2400], [0, 0]),
    ]
    rooms = [
        room(
            1,
            [[0, 0], [1000, 0], [1000, 2400], [0, 2400]],
            ["W-001", "W-002", "W-003", "W-004"],
            program="bedroom",
        )
    ]
    doors = [door(1, "W-001", door_offset, width=door_width)]
    if block_adjacent:
        doors.append(door(2, "W-002", 400.0, width=700.0))  # covers W-002 offsets 50..750
    return assemble(walls, doors, rooms, [])


def test_e3_corner_fallback_on_the_adjacent_wall():
    by_door, result = switches(narrow_room(500.0, 762.0))
    sw = by_door[
        "D-001"
    ]  # latch 881 + 150 = 1031 > 950: illegal -> latch corner (1000,0) -> W-002 @ 150
    assert (sw.host_wall_id, sw.offset) == ("W-002", 300.0)  # E3_CORNER_FALLBACK_MM from the corner
    assert any(
        i.code == "switch_corner_fallback" and i.refs == ["D-001", "W-002"] for i in result.items
    )


def test_e3_hinge_side_fallback_is_flagged():
    by_door, result = switches(narrow_room(600.0, 762.0, block_adjacent=True))
    sw = by_door["D-001"]  # hinge 219 - 150 = 69: legal on the 1220 run
    assert (sw.host_wall_id, sw.offset) == ("W-001", 69.0)
    assert any(i.code == "switch_hinge_side" and i.refs == ["D-001"] for i in result.items)


def test_e3_unplaceable_is_flagged_not_forced():
    by_door, result = switches(narrow_room(500.0, 900.0, block_adjacent=True))
    assert "D-001" not in by_door  # hinge 50 - 150 < 0, latch 950 + 150 > 1000, corner blocked
    assert any(i.code == "switch_unplaceable" and i.refs == ["D-001"] for i in result.items)
    assert "D-002" in by_door  # the blocking door on W-002 still gets its own switch


def test_one_switch_per_door_and_pocket_doors_follow_the_same_convention():
    layout = two_rooms_shared_wall(
        door_spec={
            "offset": 1500.0,
            "width": 1700.0,
            "swing": "L",
            "revit_type": "CHPT_Door_Pocket_PLACEHOLDER",
        }
    )
    by_door, _r = switches(layout)
    assert by_door["D-001"].offset == 1500.0 + 850.0 + 150.0  # latch jamb + 150
    assert len([d for d in by_door.values()]) == len(layout["doors"])
