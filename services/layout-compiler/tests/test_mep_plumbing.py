"""P-1..P-4 (Part G) on synthetic apartments + the golden chain: wet-wall
consolidation, λ unit-sanity, riser tie-break, SI-8 exclusion, FU-weighted stack
position, door-span snapping, size-dependent slope, L_max prune + second stack,
branch tree uniqueness/z-profile, blocking items, bounded iterations."""

from __future__ import annotations

import copy

import pytest
from helpers import door, room, wall
from hypothesis import given, settings
from hypothesis import strategies as st
from mep_helpers import CONFIRMATIONS, WET, assemble, commit0_for, fixture, two_baths

from layout_compiler.mep import plumbing as plumbing_mod
from layout_compiler.mep.constants import LAMBDA_FU_PER_MM
from layout_compiler.mep.inputs import resolve_inputs
from layout_compiler.mep.plumbing import l_max_mm, plan_plumbing, stack_diameter


def plan(layout, confirmations=CONFIRMATIONS, walls=None):
    inputs = resolve_inputs(layout, commit0_for(layout), confirmations, walls or {})
    return inputs, plan_plumbing(inputs)


def test_l_max_uses_the_size_dependent_slope():
    assert round(l_max_mm(300.0, 76.0, 150.0), 1) == 7115.4  # 1/8 in/ft at 3in
    assert round(l_max_mm(300.0, 38.0, 150.0), 1) == 5384.6  # 1/4 in/ft below 3in
    assert round(l_max_mm(300.0, 32.0, 150.0), 1) == 5673.1


def test_p1_wet_wall_consolidation_shared_wall_wins():
    inputs, result = plan(two_baths())
    assert inputs.blocking() == []
    assert len(result.stacks) == 1
    stack = result.stacks[0]
    assert stack.wall_id == "W-005" and stack.fixture_ids == ["F-001", "F-002", "F-003"]
    assert stack.score_fu == 9.0 and stack.riser_bias == 0.0
    assert stack.p1_ranking[0] == ("W-005", 9.0)
    assert {s for _w, s in stack.p1_ranking[1:]} == {5.0, 4.0}  # A's own walls 5, B's 4
    assert stack.diameter == 76.0  # a wc is served
    assert result.counters["p1_iterations"] == 1


@settings(max_examples=200, deadline=None)
@given(distance=st.floats(min_value=0.0, max_value=20000.0))
def test_p1_riser_bias_unit_sanity(distance: float):
    """λ = 0.0005 FU/mm ≡ 0.5 FU/m: over any in-apartment distance the bias stays the
    same order of magnitude as fixture-unit scores (1..20 FU), never dominating them."""
    bias = LAMBDA_FU_PER_MM * distance
    assert 0.0 <= bias <= 10.0
    assert LAMBDA_FU_PER_MM * 1000.0 == 0.5


def test_p1_riser_bias_decides_a_tie():
    layout = two_baths()
    # drop bath B so every wall of bath A ties at 5 FU; a sanitary riser hugs W-004
    layout["rooms"] = [layout["rooms"][0]]
    layout["furniture"] = [e for e in layout["furniture"] if e["room_id"] == "R-001"]
    layout["risers"] = [{"id": "RS-01", "type": "sanitary", "center": [-100.0, 1500.0]}]
    _inputs, result = plan(layout)
    (stack,) = result.stacks
    assert stack.wall_id == "W-004"
    assert stack.riser_bias == pytest.approx(0.05)  # 0.0005 * 100 mm
    assert stack.score_fu == pytest.approx(4.95)


def test_p1_tiebreak_prefers_wet_wall_then_closer_fixtures_then_smaller_id():
    layout = two_baths()
    layout["rooms"] = [layout["rooms"][0]]
    layout["furniture"] = [e for e in layout["furniture"] if e["room_id"] == "R-001"]
    _inputs, result = plan(layout)
    assert result.stacks[0].wall_id == "W-005"  # the only wet-flagged wall among the 5.0 ties
    for w in layout["walls"]:
        w.pop("is_wet_wall", None)
    _inputs, result = plan(layout)
    # no wet flag: the wall closest to the FU-weighted fixtures (they back onto x=2400)
    assert result.stacks[0].wall_id == "W-005"


def test_p1_excludes_si8_flagged_walls():
    layout = two_baths()
    layout["rooms"] = [layout["rooms"][0]]
    layout["furniture"] = [e for e in layout["furniture"] if e["room_id"] == "R-001"]
    flags = {"W-005": "is_demising", "W-001": "is_exterior", "W-003": "is_load_bearing"}
    for w in layout["walls"]:
        if w["id"] in flags:
            w[flags[w["id"]]] = True
    _inputs, result = plan(layout)
    assert result.stacks[0].wall_id == "W-004"
    for w in layout["walls"]:
        if w["id"] == "W-004":
            w["is_exterior"] = True
    _inputs, result = plan(layout)
    assert result.stacks == []
    assert [i.code for i in result.items if i.severity == "blocking"] == ["no_wet_wall_candidate"]


def test_p3_stack_position_is_fu_weighted():
    layout = two_baths()
    layout["rooms"] = [layout["rooms"][0]]
    layout["furniture"] = [e for e in layout["furniture"] if e["room_id"] == "R-001"]
    _inputs, result = plan(layout)
    (stack,) = result.stacks
    # wc foot at offset 800 (4 FU), lav foot at 2200 (1 FU) along W-005 (0,0 -> 0,3000)
    assert stack.feet == {"F-001": 800.0, "F-002": 2200.0}
    assert stack.offset == pytest.approx(1080.0)
    assert stack.snapped is False


def test_p3_snaps_out_of_a_door_span():
    layout = two_baths()
    layout["rooms"] = [layout["rooms"][0]]
    layout["furniture"] = [e for e in layout["furniture"] if e["room_id"] == "R-001"]
    layout["doors"].append(door(3, "W-005", 1080, width=711.0))
    _inputs, result = plan(layout)
    (stack,) = result.stacks
    # span 724.5..1435.5 +/- (38 + 50): edges 636.5 / 1523.5 are equidistant -> smaller wins
    assert stack.snapped is True and stack.offset == pytest.approx(636.5)
    assert any(i.code == "p3_snapped" and i.refs == ["P-001"] for i in result.items)
    assert result.counters["snap_steps"] == 1


def test_p4_lmax_violation_prunes_and_forces_a_second_stack():
    walls = [
        wall(1, [0, 0], [2400, 0]),
        wall(5, [2400, 0], [2400, 6000], revit_type=WET, is_wet_wall=True),
        wall(3, [2400, 6000], [0, 6000]),
        wall(4, [0, 6000], [0, 0]),
    ]
    rooms = [
        room(
            1,
            [[0, 0], [2400, 0], [2400, 6000], [0, 6000]],
            ["W-001", "W-005", "W-003", "W-004"],
            program="bathroom",
            wet_zone=True,
        ),
    ]
    placed = [
        fixture(1, "R-001", "wc", [1974.0, 200.0]),
        fixture(2, "R-001", "lav", [2099.0, 5800.0]),
    ]
    layout = assemble(walls, [door(1, "W-003", 1200)], rooms, placed)
    # h_plenum 250: L_max(lav, 32mm) = (250-32-150)/0.0208 = 3269 < along 4480 -> prune
    _inputs, result = plan(layout, {"panel": [50.0, 3000.0], "slab_to_slab_mm": 2950.0})
    assert [s.fixture_ids for s in result.stacks] == [["F-001"], ["F-002"]]
    assert [s.offset for s in result.stacks] == [200.0, 5800.0]
    assert result.counters["p4_prune_steps"] == 1 and result.counters["p1_iterations"] == 2
    assert any(i.code == "p4_prune" and i.refs == ["F-002", "W-005"] for i in result.items)


def test_plenum_too_shallow_is_blocking_and_plans_nothing():
    _inputs, result = plan(two_baths(), {"panel": [50.0, 1500.0], "slab_to_slab_mm": 2800.0})
    assert _inputs.blocking() == ["plenum_too_shallow"]
    assert result.stacks == [] and result.segments == []


def test_branch_tree_segments_are_unique_and_the_z_profile_is_honest():
    inputs, result = plan(two_baths())
    (stack,) = result.stacks
    segs = result.segments
    assert [s.id for s in segs] == [f"P-{i:03d}" for i in range(2, 2 + len(segs))]
    # no two along-wall segments overlap with positive length
    alongs = [s for s in segs if s.cls == "along"]
    for i, a in enumerate(alongs):
        for b in alongs[i + 1 :]:
            lo = max(min(a.start[1], a.end[1]), min(b.start[1], b.end[1]))
            hi = min(max(a.start[1], a.end[1]), max(b.start[1], b.end[1]))
            assert hi - lo <= 1e-6
    # every segment slopes DOWN toward the stack (start higher than end)
    assert all(s.start[2] > s.end[2] for s in segs)
    # governing fixture: pipe top at floor_z - h_fitting; everything else no higher
    tops = {}
    for s in segs:
        for fid in s.fixture_ids:
            tops[fid] = max(tops.get(fid, -1e9), s.start[2] + s.diameter / 2)
    assert max(tops.values()) == pytest.approx(inputs.floor_z - inputs.h_fitting, abs=0.1)
    # the two wcs share the foot at offset 800 -> one 76 mm trunk to the stack; the lav
    # approaches from the other side alone at its own 32 mm / 1/4 in-ft
    shared = [s for s in segs if set(s.fixture_ids) == {"F-001", "F-003"}]
    assert shared and all(s.diameter == 76.0 and s.slope == 0.0104 for s in shared)
    lav_only = [s for s in segs if s.fixture_ids == ["F-002"]]
    assert lav_only and all(s.diameter == 32.0 and s.slope == 0.0208 for s in lav_only)
    routes = {r["fixture_id"]: r for r in result.fixture_routes}
    assert routes["F-001"]["path_mm"] == pytest.approx(
        routes["F-001"]["leg_mm"] + routes["F-001"]["along_mm"]
    )
    assert routes["F-001"]["L_mm"] == routes["F-001"]["along_mm"]  # PIN-08 spec-literal
    assert any(i.code == "wye_manual" and i.refs == [stack.id] for i in result.items)


def test_stack_diameter_rule():
    inputs, _ = plan(two_baths())
    by_id = {f.id: f for f in inputs.fixtures}
    assert stack_diameter([by_id["F-002"]]) == 51.0  # lav alone: minimum
    assert stack_diameter([by_id["F-001"]]) == 76.0  # wc


def test_p1_iterations_exceeded_is_a_blocking_item(monkeypatch):
    monkeypatch.setattr(plumbing_mod, "MAX_P1_ITERATIONS", 1)
    # two disjoint wet rooms need two iterations
    walls = [
        wall(1, [0, 0], [2400, 0]),
        wall(2, [2400, 0], [2400, 3000]),
        wall(3, [2400, 3000], [0, 3000]),
        wall(4, [0, 3000], [0, 0]),
        wall(5, [8000, 0], [10400, 0]),
        wall(6, [10400, 0], [10400, 3000]),
        wall(7, [10400, 3000], [8000, 3000]),
        wall(8, [8000, 3000], [8000, 0]),
    ]
    rooms = [
        room(
            1,
            [[0, 0], [2400, 0], [2400, 3000], [0, 3000]],
            ["W-001", "W-002", "W-003", "W-004"],
            program="bathroom",
            wet_zone=True,
        ),
        room(
            2,
            [[8000, 0], [10400, 0], [10400, 3000], [8000, 3000]],
            ["W-005", "W-006", "W-007", "W-008"],
            program="bathroom",
            wet_zone=True,
        ),
    ]
    placed = [
        fixture(1, "R-001", "wc", [1974.0, 800.0]),
        fixture(2, "R-002", "wc", [9974.0, 800.0]),
    ]
    layout = assemble(walls, [door(1, "W-003", 1200), door(2, "W-007", 9200 - 8000)], rooms, placed)
    _inputs, result = plan(layout)
    assert len(result.stacks) == 1
    assert [i.code for i in result.items if i.severity == "blocking"] == ["p1_iterations_exceeded"]
    assert result.items[-1].refs == ["F-002"] or any(i.refs == ["F-002"] for i in result.items)


def test_deadline_check_is_polled():
    calls = []

    def tick():
        calls.append(1)

    inputs = resolve_inputs(two_baths(), commit0_for(two_baths()), CONFIRMATIONS, {}, tick)
    plan_plumbing(inputs, tick)
    assert len(calls) >= 2


def test_layout_is_never_mutated():
    layout = two_baths()
    before = copy.deepcopy(layout)
    plan(layout)
    assert layout == before
