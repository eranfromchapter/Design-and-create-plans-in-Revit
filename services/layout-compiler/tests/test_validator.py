"""Validator rules, each with a named failing case; the minimal layout passes."""

from __future__ import annotations

from helpers import NEW_WALL, door, make_layout, room, wall

from layout_compiler.validator import validate_layout


def test_minimal_layout_is_valid():
    assert validate_layout(make_layout()) == []


def test_phase_must_be_new():
    layout = make_layout()
    layout["meta"]["phase"] = "existing"
    assert any("must be" in e and "new" in e for e in validate_layout(layout))


def test_rooms_required_for_compiled_layouts():
    layout = make_layout(rooms=[], doors=[])
    assert any(e.startswith("rooms:") for e in validate_layout(layout))


def test_unknown_host_wall_is_referential_error():
    layout = make_layout(doors=[door(1, "W-099", 2000)])
    assert any("unknown host wall W-099" in e for e in validate_layout(layout))


def test_generated_wall_with_asbuilt_type_rejected():
    layout = make_layout()
    layout["walls"][0]["revit_type"] = "CHPT_AsBuilt_200mm_PLACEHOLDER"
    errors = validate_layout(layout)
    assert any("closed vocabulary" in e for e in errors)


def test_wall_without_source_rejected():
    layout = make_layout()
    del layout["walls"][0]["source"]
    assert any("must set source" in e for e in validate_layout(layout))


def test_unknown_door_type_rejected():
    layout = make_layout(doors=[door(1, "W-001", 2000, revit_type="Single-Flush 36x80")])
    assert any("not in any catalog" in e for e in validate_layout(layout))


def test_door_overrunning_host_rejected():
    layout = make_layout(doors=[door(1, "W-001", 3800)])  # 3800+457.5 > 4000
    assert any("outside host" in e for e in validate_layout(layout))


def test_boundary_edge_off_every_wall_rejected():
    layout = make_layout()
    layout["rooms"][0]["boundary"] = [
        [0, 0],
        [4000, 0],
        [4000, 3500],
        [0, 3500],
    ]  # north edge floats
    assert any("lies on no boundary wall" in e for e in validate_layout(layout))


def test_boundary_repeating_first_vertex_rejected():
    layout = make_layout()
    layout["rooms"][0]["boundary"] = [[0, 0], [4000, 0], [4000, 3000], [0, 3000], [0, 0]]
    assert any("implicit closure" in e for e in validate_layout(layout))


def test_bowtie_boundary_rejected():
    layout = make_layout()
    layout["rooms"][0]["boundary"] = [[0, 0], [4000, 3000], [4000, 0], [0, 3000]]
    assert any("simple positive-area" in e for e in validate_layout(layout))


def test_narrow_room_fails_min_width_under_circulation_erosion():
    walls = [
        wall(1, [0, 0], [4000, 0]),
        wall(2, [4000, 0], [4000, 800]),
        wall(3, [4000, 800], [0, 800]),
        wall(4, [0, 800], [0, 0]),
    ]
    layout = make_layout(
        walls=walls,
        doors=[door(1, "W-001", 2000)],
        rooms=[room(1, [[0, 0], [4000, 0], [4000, 800], [0, 800]], [w["id"] for w in walls])],
    )
    assert any("min width violated" in e for e in validate_layout(layout))


def test_dumbbell_room_with_doors_in_both_lobes_fails_circulation_connectivity():
    # two 2000x2000 lobes joined by a 200mm neck; doors in each lobe's south wall
    boundary = [
        [0, 0],
        [2000, 0],
        [2000, 900],
        [3000, 900],
        [3000, 0],
        [5000, 0],
        [5000, 2000],
        [3000, 2000],
        [3000, 1100],
        [2000, 1100],
        [2000, 2000],
        [0, 2000],
    ]
    ring = [*boundary, boundary[0]]
    walls = [wall(i + 1, ring[i], ring[i + 1]) for i in range(len(boundary))]
    layout = make_layout(
        walls=walls,
        doors=[door(1, "W-001", 1000), door(2, "W-006", 1000)],
        rooms=[room(1, boundary, [w["id"] for w in walls])],
    )
    errors = validate_layout(layout)
    assert any("disconnected circulation" in e for e in errors)


def test_overlapping_rooms_rejected():
    walls = [
        wall(1, [0, 0], [4000, 0]),
        wall(2, [4000, 0], [4000, 3000]),
        wall(3, [4000, 3000], [0, 3000]),
        wall(4, [0, 3000], [0, 0]),
        wall(5, [2000, 0], [2000, 3000]),
    ]
    ids = [w["id"] for w in walls]
    layout = make_layout(
        walls=walls,
        doors=[door(1, "W-001", 1000)],
        rooms=[
            room(1, [[0, 0], [2000, 0], [2000, 3000], [0, 3000]], ids),
            # overlaps R-001 between x 1000..2000
            room(2, [[1000, 0], [4000, 0], [4000, 3000], [1000, 3000]], ids),
        ],
    )
    assert any("boundaries overlap" in e for e in validate_layout(layout))


def test_scan_walls_resolve_via_asbuilt_catalog():
    layout = make_layout()
    layout["walls"][0].update(
        {
            "revit_type": "CHPT_AsBuilt_200mm_PLACEHOLDER",
            "source": "scan",
            "as_built_thickness": 200.0,
        }
    )
    assert validate_layout(layout) == []
    layout["walls"][0]["revit_type"] = NEW_WALL  # a scan wall with generated vocab is wrong
    assert any("not in asbuilt_types" in e for e in validate_layout(layout))


def test_errors_are_sorted_and_stable():
    layout = make_layout(doors=[door(1, "W-099", 2000), door(2, "W-098", 100)])
    first = validate_layout(layout)
    assert first == sorted(first) == validate_layout(layout)
