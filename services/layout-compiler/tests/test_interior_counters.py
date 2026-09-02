"""SI-6 iteration-bound counter assertions (PLAN.md Phase 5 acceptance bullet 3):
the greedy tries AT MOST 162 candidates per wall and the spiral AT MOST 324 —
asserted from the diagnostics counters on exhausting items, exact on exhaustion."""

from __future__ import annotations

from helpers import make_layout

from layout_compiler.interior import MAX_CANDIDATES_PER_WALL, SPIRAL_CAP, legalize_furniture


def oversized(wall_seeking: bool) -> dict:
    """A queen bed footprint cannot fit a 2000x1500 slot in the 4000x3000 room?
    It can — so use a footprint bigger than the room: a sofa is placeable, the
    bed is not once the room shrinks. Simplest exhausting item: propose the bed
    into a room where covers() can never pass."""
    return {
        "id": "F-001",
        "room_id": "R-001",
        "kind": "bed",
        "revit_family": "CHPT_Bed_PLACEHOLDER",
        "revit_type": "Queen_1524x2032_PLACEHOLDER",
        "center": [1000.0, 1000.0],
        "rotation_deg": 0.0,
        "footprint": [1524.0, 2032.0],
        "wall_seeking": wall_seeking,
    }


def tiny_room_layout() -> dict:
    """A 1800x1400 'other' room: the queen (1524x2032) fails covers() in every
    orientation, so both search modes exhaust their full candidate budgets."""
    from helpers import door, room, wall

    walls = [
        wall(1, [0, 0], [1800, 0]),
        wall(2, [1800, 0], [1800, 1400]),
        wall(3, [1800, 1400], [0, 1400]),
        wall(4, [0, 1400], [0, 0]),
    ]
    return make_layout(
        walls=walls,
        doors=[door(1, "W-001", 900, width=762)],
        rooms=[
            room(
                1,
                [[0, 0], [1800, 0], [1800, 1400], [0, 1400]],
                [w["id"] for w in walls],
                program="other",
            )
        ],
    )


def test_wall_candidates_capped_at_162_per_wall():
    outcome = legalize_furniture([oversized(wall_seeking=True)], tiny_room_layout())
    assert [u["item"]["id"] for u in outcome.unplaced] == ["F-001"]
    diag = outcome.diagnostics["items"][0]
    assert diag["walls_tried"] == 4
    assert set(diag["candidates_per_wall"].values()) == {MAX_CANDIDATES_PER_WALL}
    assert diag["candidates_tried"] == 4 * MAX_CANDIDATES_PER_WALL == 648


def test_spiral_capped_at_324():
    outcome = legalize_furniture([oversized(wall_seeking=False)], tiny_room_layout())
    assert [u["item"]["id"] for u in outcome.unplaced] == ["F-001"]
    diag = outcome.diagnostics["items"][0]
    assert diag["spiral_tried"] == SPIRAL_CAP == 324
