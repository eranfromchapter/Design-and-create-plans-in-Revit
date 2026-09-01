"""geometry.py unit pins: the shared primitives the validator AND the Phase 5
interior placer both consume — including byte-identical circulation error
strings (the repair loop feeds them to the LLM verbatim)."""

from __future__ import annotations

from shapely.geometry import Polygon

from layout_compiler.geometry import (
    circulation_errors,
    clearance_blob,
    furniture_rect,
    pt_on_wall,
    room_free_space,
    room_thresholds,
    wall_len,
    wall_thickness_of,
)

WALL = {
    "id": "W-001",
    "start": [0.0, 0.0],
    "end": [4000.0, 0.0],
    "revit_type": "CHPT_Partition_92mm_PLACEHOLDER",
}


def test_pt_on_wall_convention():
    assert pt_on_wall(WALL, 1000.0) == (1000.0, 0.0)
    assert pt_on_wall({**WALL, "end": [0.0, 0.0]}, 500.0) == (0.0, 0.0)  # zero-length guard
    assert wall_len(WALL) == 4000.0


def test_wall_thickness_resolution():
    assert wall_thickness_of(WALL) == 92.0  # catalog
    assert wall_thickness_of({**WALL, "as_built_thickness": 250.0}) == 250.0  # scan wins
    assert wall_thickness_of({**WALL, "revit_type": "nope"}) is None


def test_furniture_rect_rotation_semantics():
    item = {"center": [1000.0, 1000.0], "rotation_deg": 90.0, "footprint": [2000.0, 600.0]}
    rect = furniture_rect(item)
    minx, miny, maxx, maxy = rect.bounds
    # width axis rotated CCW onto y: bbox becomes 600 x 2000
    assert (round(maxx - minx), round(maxy - miny)) == (600, 2000)
    assert rect.centroid.coords[0] == (1000.0, 1000.0)


def test_clearance_blob_inflates_all_sides():
    item = {"center": [0.0, 0.0], "rotation_deg": 0.0, "footprint": [1000.0, 1000.0]}
    blob = clearance_blob({**item, "clearance_front": 500.0})
    minx, miny, maxx, maxy = blob.bounds
    assert (round(maxx - minx), round(maxy - miny)) == (2000, 2000)
    assert clearance_blob(item).equals(furniture_rect(item))  # absent => 0


def test_room_free_space_subtracts_blobs():
    room = Polygon([(0, 0), (4000, 0), (4000, 3000), (0, 3000)])
    item = {"center": [2000.0, 1500.0], "rotation_deg": 0.0, "footprint": [1000.0, 1000.0]}
    free = room_free_space(room, [item])
    assert round(room.area - free.area) == 1000 * 1000


def test_thresholds_only_on_this_rooms_edge():
    room = {"id": "R-001", "boundary_wall_ids": ["W-001"], "boundary": None}
    polygon = Polygon([(0, 0), (4000, 0), (4000, 3000), (0, 3000)])
    long_wall = {**WALL, "end": [8000.0, 0.0]}
    doors = [
        {"id": "D-001", "host_wall_id": "W-001", "offset": 2000.0},
        {"id": "D-002", "host_wall_id": "W-001", "offset": 6000.0},  # beyond the room
        {"id": "D-003", "host_wall_id": "W-099", "offset": 100.0},  # not a boundary wall
    ]
    found = room_thresholds(room, polygon, doors, {"W-001": long_wall})
    assert [door_id for door_id, _ in found] == ["D-001"]


def test_circulation_error_strings_are_validator_stable():
    tiny = Polygon([(0, 0), (800, 0), (800, 800), (0, 800)])
    vanish = circulation_errors("R-001", tiny, [("D-001", (400.0, 0.0))], 900.0)
    assert vanish == [
        "rooms.R-001: free space vanishes under circulation erosion (900mm) — min width violated"
    ]
    # two lobes joined by nothing: disconnected components
    lobes = Polygon([(0, 0), (2000, 0), (2000, 2000), (0, 2000)]).union(
        Polygon([(5000, 0), (7000, 0), (7000, 2000), (5000, 2000)])
    )
    split = circulation_errors(
        "R-002", lobes, [("D-001", (1000.0, 0.0)), ("D-002", (6000.0, 0.0))], 900.0
    )
    assert split == [
        "rooms.R-002: door thresholds fall in disconnected circulation components "
        "(circulation_min 900mm)"
    ]
    far = circulation_errors("R-003", lobes, [("D-001", (6000.0, 5000.0))], 900.0)
    assert far == [
        "rooms.R-003: door threshold (6000,5000) unreachable from the room's circulation space"
    ]
    assert circulation_errors("R-004", tiny, [], 900.0) == []  # no thresholds, no verdicts
