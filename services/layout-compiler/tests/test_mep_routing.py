"""E-4 (Part G): Dijkstra on the wall-centerline graph from the panel — the wet-stack
exclusion prism is impassable, fire-rated (or demising) penetrations cost 4000 mm
equivalent (pass-through AND turn-in; arriving along the rated wall is free), nodes
within 1 mm canonicalize, the raceway tree has unique segments, states are bounded
and ties deterministic."""

from __future__ import annotations

import pytest
from helpers import room, wall
from mep_helpers import assemble, commit0_for

from layout_compiler.mep.constants import E4_PENETRATION_PENALTY_MM
from layout_compiler.mep.electrical import Device
from layout_compiler.mep.inputs import resolve_inputs
from layout_compiler.mep.routing import build_graph, dijkstra, route_home_runs


def device(
    i: int, wall_id: str, offset: float, room_id: str = "R-001", height: float = 380.0
) -> Device:
    return Device(
        kind="receptacle",
        rule="E-1",
        room_id=room_id,
        host_wall_id=wall_id,
        offset=offset,
        height_afl=height,
        face="left",
        id=f"E-{i:03d}",
    )


def single_room():
    walls = [
        wall(1, [0, 0], [4000, 0]),
        wall(2, [4000, 0], [4000, 3000]),
        wall(3, [4000, 3000], [0, 3000]),
        wall(4, [0, 3000], [0, 0]),
    ]
    rooms = [
        room(
            1,
            [[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
            ["W-001", "W-002", "W-003", "W-004"],
            program="living",
        )
    ]
    return assemble(walls, [], rooms, [])


def inputs_for(layout, panel):
    return resolve_inputs(layout, commit0_for(layout), {"panel": panel, "slab_to_slab_mm": 3000.0})


def test_e4_route_avoids_the_wet_stack_prism():
    inputs = inputs_for(single_room(), [50.0, 1500.0])  # panel foot (0, 1500) on W-004
    stacks = [("W-001", 1500.0)]  # square x 1200..1800 on the south wall
    result = route_home_runs(inputs, [device(1, "W-001", 3000.0)], stacks)
    (run,) = result.home_runs
    # the direct way along the south wall is blocked: the route goes round the north
    assert all(not (y == 0.0 and 1200.0 < x < 1800.0) for x, y in run.nodes)
    assert (4000.0, 3000.0) in run.nodes and (0.0, 3000.0) in run.nodes
    assert run.length_mm == pytest.approx(1500 + 4000 + 3000 + 1000)  # up, across, down, back
    assert run.penetrations == 0 and run.cost == pytest.approx(run.length_mm)


def test_device_inside_the_stack_square_is_unroutable():
    inputs = inputs_for(single_room(), [50.0, 1500.0])
    result = route_home_runs(inputs, [device(1, "W-001", 1600.0)], [("W-001", 1500.0)])
    assert result.home_runs == [] and result.drops == []
    assert [i.code for i in result.items if i.code == "device_unroutable"] == ["device_unroutable"]


def spine_plan(height: float, rated_flag: dict | None = None):
    """Four rooms around a rated spine W-005 (x=2400) with T-junction partitions
    W-008/W-009 at y = height/2 (a node strictly INSIDE the spine)."""
    h, m = height, height / 2
    walls = [
        wall(1, [0, 0], [4800, 0]),
        wall(3, [4800, h], [0, h]),
        wall(4, [0, h], [0, 0]),
        wall(6, [4800, 0], [4800, h]),
        wall(5, [2400, 0], [2400, h], **(rated_flag or {"fire_rating_hr": 1})),
        wall(8, [0, m], [2400, m]),
        wall(9, [2400, m], [4800, m]),
    ]
    rooms = [
        room(1, [[0, 0], [2400, 0], [2400, m], [0, m]], ["W-001", "W-005", "W-008", "W-004"]),
        room(2, [[0, m], [2400, m], [2400, h], [0, h]], ["W-008", "W-005", "W-003", "W-004"]),
        room(3, [[2400, 0], [4800, 0], [4800, m], [2400, m]], ["W-001", "W-006", "W-009", "W-005"]),
        room(4, [[2400, m], [4800, m], [4800, h], [2400, h]], ["W-009", "W-006", "W-003", "W-005"]),
    ]
    return assemble(walls, [], rooms, [])


@pytest.mark.parametrize(
    ("height", "expect_penetration"),
    [(3000.0, False), (5000.0, True)],  # detour costs 4850 + h vs straight 4750 + 4000
)
def test_e4_fire_rated_penalty_is_4000_equivalent(height: float, expect_penetration: bool):
    m = height / 2
    inputs = inputs_for(spine_plan(height), [50.0, m])  # panel foot (50, m) on W-008
    assert inputs.panel_wall_id == "W-008"
    result = route_home_runs(inputs, [device(1, "W-006", m, room_id="R-003")], [])
    (run,) = result.home_runs
    if expect_penetration:
        assert run.penetrations == 1
        assert run.cost == pytest.approx(run.length_mm + E4_PENETRATION_PENALTY_MM)
        assert (2400.0, m) in run.nodes  # straight through the rated spine
    else:
        assert run.penetrations == 0 and run.cost == pytest.approx(run.length_mm)
        assert (2400.0, m) not in run.nodes  # detoured round the south
        assert (0.0, 0.0) in run.nodes and (4800.0, 0.0) in run.nodes


@pytest.mark.parametrize(
    ("height", "expect_turn_in"),
    [(3000.0, False), (12000.0, True)],
)
def test_e4_turn_in_to_the_rated_wall_is_penalized_arriving_along_it_is_free(
    height: float, expect_turn_in: bool
):
    """Device ON the spine 500 above the T-junction. Turning into W-005 at the junction
    from W-008 costs 4000; arriving along W-005 from an end is free. In the 3000 mm plan
    the free route round the north (4950) beats the turn-in (6850); in the 12000 mm plan
    every free route exceeds 13000, so the penalized turn-in wins and is counted."""
    m = height / 2
    inputs = inputs_for(spine_plan(height), [50.0, m])
    result = route_home_runs(inputs, [device(1, "W-005", m + 500.0, room_id="R-002")], [])
    (run,) = result.home_runs
    if expect_turn_in:
        assert run.penetrations == 1
        assert run.cost == pytest.approx(run.length_mm + E4_PENETRATION_PENALTY_MM)
        assert run.length_mm == pytest.approx(2350 + 500)
        assert (2400.0, m) in run.nodes
    else:
        assert run.penetrations == 0 and run.cost == pytest.approx(run.length_mm)
        assert run.length_mm == pytest.approx(50 + 1500 + 2400 + 1000)
        assert (2400.0, height) in run.nodes  # arrives along the spine from its north end


def test_e4_demising_wall_counts_as_rated():
    inputs = inputs_for(spine_plan(5000.0, {"is_demising": True}), [50.0, 2500.0])
    result = route_home_runs(inputs, [device(1, "W-006", 2500.0, room_id="R-003")], [])
    (run,) = result.home_runs
    assert run.penetrations == 1 and run.cost == pytest.approx(run.length_mm + 4000.0)


def test_e4_nodes_within_1mm_canonicalize():
    inputs = inputs_for(spine_plan(3000.0), [50.0, 1500.0])
    # a device foot 0.4 mm from the T-junction node collapses onto it
    graph = build_graph(
        inputs, [], [device(1, "W-005", 1500.4, room_id="R-002")], (50.0, 1500.0), "W-008"
    )
    near = [n for n in graph.nodes if abs(n[0] - 2400.0) <= 1.0 and abs(n[1] - 1500.0) <= 1.0]
    assert len(near) == 1
    result = route_home_runs(inputs, [device(1, "W-005", 1500.4, room_id="R-002")], [])
    assert len(result.home_runs) == 1


def test_e4_raceway_tree_segments_are_unique_and_drops_vertical():
    inputs = inputs_for(single_room(), [50.0, 1500.0])
    devices = [
        device(1, "W-001", 1000.0),
        device(2, "W-001", 3000.0),
        device(3, "W-002", 1500.0),
        device(4, "W-003", 2000.0, height=1220.0),
    ]
    result = route_home_runs(inputs, devices, [])
    assert len(result.drops) == 4 and len(result.home_runs) == 4
    for drop, dev in zip(result.drops, devices, strict=False):
        (x0, y0, z0), (x1, y1, z1) = drop["path"]
        assert (x0, y0) == (x1, y1) and (z0, z1) == (dev.height_afl, 2600.0)
        assert drop["device_id"] == dev.id
    segments = []
    for trunk in result.trunks:
        assert all(p[2] == 2600.0 for p in trunk["path"])
        for a, b in zip(trunk["path"], trunk["path"][1:], strict=False):
            segments.append(tuple(sorted([tuple(a[:2]), tuple(b[:2])])))
    assert len(segments) == len(set(segments))  # no conduit segment emitted twice
    # every conduit segment lies on a wall centerline of the room
    for (ax, ay), (bx, by) in segments:
        assert ax == bx or ay == by
    # drops pair with devices in id order: Q-001..Q-004, trunks continue the numbering
    assert [d["id"] for d in result.drops] == ["Q-001", "Q-002", "Q-003", "Q-004"]
    assert result.trunks[0]["id"] == "Q-005"


def test_e4_states_bounded_and_output_deterministic():
    inputs = inputs_for(spine_plan(3000.0), [50.0, 1500.0])
    devices = [
        device(1, "W-006", 1500.0, room_id="R-003"),
        device(2, "W-001", 600.0),
        device(3, "W-003", 4000.0, room_id="R-004"),
    ]
    graph = build_graph(inputs, [], devices, inputs.panel_node, inputs.panel_wall_id)
    _dist, _prev, states = dijkstra(graph, (50.0, 1500.0), "W-008")
    walls = {w for ws in graph.node_walls.values() for w in ws}
    assert states <= len(graph.nodes) * (len(walls) + 1)
    first = route_home_runs(inputs, devices, [])
    second = route_home_runs(inputs, devices, [])
    assert [h.to_dict() for h in first.home_runs] == [h.to_dict() for h in second.home_runs]
    assert first.trunks == second.trunks and first.counters == second.counters


def test_no_panel_means_no_routing_and_no_extra_items():
    layout = single_room()
    inputs = resolve_inputs(layout, commit0_for(layout), {"slab_to_slab_mm": 3000.0})
    assert inputs.blocking() == ["panel_missing"]
    result = route_home_runs(inputs, [device(1, "W-001", 3000.0)], [])
    assert result.home_runs == [] and result.items == []
