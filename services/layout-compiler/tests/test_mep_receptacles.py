"""E-1 (Part G): the spacing kernel as a hypothesis property with the 1 mm epsilon,
exact-limit cases, the explicit N = 1 branch, the 300 mm dedupe, the 610 mm run
floor, window/counter run breaks, corridor + laundry single-device pins, coverage
notes."""

from __future__ import annotations

from helpers import door, room, wall
from hypothesis import given, settings
from hypothesis import strategies as st
from mep_helpers import (
    CONFIRMATIONS,
    assemble,
    commit0_for,
    kitchen,
    two_baths,
    two_rooms_shared_wall,
)

from layout_compiler.mep.constants import E1_INSET_MM
from layout_compiler.mep.electrical import plan_electrical, spacing_positions
from layout_compiler.mep.inputs import resolve_inputs
from layout_compiler.mep.runs import wall_runs

EPS = 1.0  # Part G: comparisons use <= with a 1 mm epsilon


def electrical(layout, confirmations=CONFIRMATIONS):
    inputs = resolve_inputs(layout, commit0_for(layout), confirmations)
    return inputs, plan_electrical(inputs)


@settings(max_examples=300, deadline=None)
@given(
    length=st.floats(min_value=610.0, max_value=40000.0),
    spacing=st.floats(min_value=50.0, max_value=8000.0),
)
def test_e1_property_spacing_epsilon(length: float, spacing: float):
    a = E1_INSET_MM
    raw = spacing_positions(length, a, spacing, dedupe=False)
    assert raw and all(0.0 <= x <= length for x in raw)
    if len(raw) == 1:
        assert raw == [length / 2] and length <= 2 * a + spacing + EPS
    else:
        assert abs(raw[0] - a) <= EPS and abs(raw[-1] - (length - a)) <= EPS
        assert all(b - c <= spacing + EPS for c, b in zip(raw, raw[1:], strict=False))
    deduped = spacing_positions(length, a, spacing)
    assert deduped == sorted(deduped) and all(0.0 <= x <= length for x in deduped)
    assert all(b - c >= 300.0 - 1e-6 for c, b in zip(deduped, deduped[1:], strict=False))
    if spacing >= 300.0:
        # coverage: with S >= the dedupe distance at most adjacent pairs merge (<= 150 mm
        # drift), so every run point stays within max(a, S/2) + 150 of a kept device;
        # below 300 the whole raw set may legitimately collapse into one device
        reach = max(a, spacing / 2) + 150.0 + EPS
        for t in [*range(0, int(length), 50), length]:
            assert min(abs(t - x) for x in deduped) <= reach
    else:
        assert len(deduped) >= 1


def test_e1_exact_limits_land_on_the_boundaries():
    a, s = E1_INSET_MM, 3660.0
    assert spacing_positions(2 * a, a, s) == [a]  # L = 2a: N = 1 -> L/2 == a exactly
    assert spacing_positions(2 * a + s, a, s) == [a, a + s]  # L = 2a + S: N = 2
    assert len(spacing_positions(2 * a + s + 1.0, a, s)) == 3


def test_e1_n1_branch_is_explicit_midpoint():
    assert spacing_positions(3000.0, E1_INSET_MM, 3660.0) == [1500.0]
    assert spacing_positions(610.0, E1_INSET_MM, 3660.0) == [305.0]
    assert spacing_positions(609.9, E1_INSET_MM, 3660.0) == []


def test_e1_dedupe_general_fixpoint():
    raw = spacing_positions(1000.0, 100.0, 100.0, dedupe=False)
    assert len(raw) == 9
    merged = spacing_positions(1000.0, 100.0, 100.0)
    assert len(merged) < len(raw)
    assert all(b - c >= 300.0 - 1e-9 for c, b in zip(merged, merged[1:], strict=False))
    assert all(0.0 <= x <= 1000.0 for x in merged)


def test_windows_break_runs_only_at_the_device_height():
    layout = two_baths()
    layout["windows"].append(
        {
            "id": "N-001",
            "host_wall_id": "W-001",
            "offset": 1200.0,
            "width": 1000.0,
            "height": 1400.0,
            "sill_height": 900.0,
            "revit_type": "CHPT_Window_DoubleHung_PLACEHOLDER",
        }
    )
    room, w1 = layout["rooms"][0], layout["walls"][0]
    assert wall_runs(layout, room, w1, 380.0) == [(0.0, 2400.0)]  # receptacle height: intact
    assert wall_runs(layout, room, w1, 1150.0) == [(0.0, 700.0), (1700.0, 2400.0)]  # counter height


def test_counter_interval_is_removed_from_e1_runs():
    _inputs, result = electrical(
        kitchen(with_casework=True), {"panel": [50.0, 1800.0], "slab_to_slab_mm": 3000.0}
    )
    e1_on_counter_wall = [
        d for d in result.devices if d.rule == "E-1" and d.host_wall_id == "W-001"
    ]
    assert e1_on_counter_wall and all(not (600.0 <= d.offset <= 3600.0) for d in e1_on_counter_wall)
    counter = [d for d in result.devices if d.rule == "E-2"]
    assert counter and all(600.0 <= d.offset <= 3600.0 and d.height_afl == 1150.0 for d in counter)


def test_outlet_spacing_below_610_skips_e1():
    layout = two_rooms_shared_wall()
    layout["constraints"]["outlet_spacing"] = 500
    inputs, result = electrical(layout)
    assert inputs.blocking() == ["outlet_spacing_invalid"]
    assert [d for d in result.devices if d.rule == "E-1"] == []


def test_corridor_gets_one_receptacle_only_when_long_enough():
    def corridor(length: float):
        walls = [
            wall(1, [0, 0], [length, 0]),
            wall(2, [length, 0], [length, 1200]),
            wall(3, [length, 1200], [0, 1200]),
            wall(4, [0, 1200], [0, 0]),
        ]
        rooms = [
            room(
                1,
                [[0, 0], [length, 0], [length, 1200], [0, 1200]],
                ["W-001", "W-002", "W-003", "W-004"],
                program="corridor",
            )
        ]
        return assemble(walls, [door(1, "W-002", 600, width=762.0)], rooms, [])

    _i, long_hall = electrical(
        corridor(4000.0), {"panel": [50.0, 600.0], "slab_to_slab_mm": 3000.0}
    )
    recs = [d for d in long_hall.devices if d.rule == "corridor"]
    assert len(recs) == 1 and recs[0].kind == "receptacle" and recs[0].height_afl == 380.0
    assert recs[0].host_wall_id in ("W-001", "W-003") and recs[0].offset == 2000.0  # midpoint
    _i, short_hall = electrical(
        corridor(2400.0), {"panel": [50.0, 600.0], "slab_to_slab_mm": 3000.0}
    )
    assert [d for d in short_hall.devices if d.rule == "corridor"] == []
    assert any(i.code == "room_without_receptacle" for i in short_hall.items)


def test_laundry_gets_one_gfci_at_counter_height():
    walls = [
        wall(1, [0, 0], [1800, 0]),
        wall(2, [1800, 0], [1800, 1800]),
        wall(3, [1800, 1800], [0, 1800]),
        wall(4, [0, 1800], [0, 0]),
    ]
    rooms = [
        room(
            1,
            [[0, 0], [1800, 0], [1800, 1800], [0, 1800]],
            ["W-001", "W-002", "W-003", "W-004"],
            program="laundry",
            wet_zone=True,
        )
    ]
    layout = assemble(walls, [door(1, "W-003", 900, width=762.0)], rooms, [])
    _i, result = electrical(layout, {"panel": [50.0, 900.0], "slab_to_slab_mm": 3000.0})
    gfcis = [d for d in result.devices if d.rule == "laundry"]
    assert len(gfcis) == 1 and gfcis[0].kind == "gfci" and gfcis[0].height_afl == 1150.0
    assert [d for d in result.devices if d.rule == "E-1"] == []


def test_room_without_receptacle_and_basin_rule_in_bathrooms():
    _i, result = electrical(two_baths())
    assert [d.rule for d in result.devices if d.room_id == "R-001" and d.kind != "switch"] == [
        "E-2-basin"
    ]
    assert any(i.code == "room_without_receptacle" and i.refs == ["R-002"] for i in result.items)
    assert not any(
        i.code == "room_without_receptacle" and i.refs == ["R-001"] for i in result.items
    )


def test_back_to_back_devices_on_a_shared_wall_shift_150():
    # both rooms are 3660 wide: N = 1 puts an E-1 device at 1830 on EACH side of W-001
    _i, result = electrical(two_rooms_shared_wall(width=3660.0))
    on_shared = sorted(
        d.offset for d in result.devices if d.host_wall_id == "W-001" and d.rule == "E-1"
    )
    assert on_shared == [1830.0, 1980.0]
    assert any(i.code == "device_backtoback_shifted" and i.refs == ["W-001"] for i in result.items)
    assert result.counters["b2b_shifts"] == 1
    faces = {
        d.offset: d.face for d in result.devices if d.host_wall_id == "W-001" and d.rule == "E-1"
    }
    assert faces == {1830.0: "left", 1980.0: "right"}  # north room is LEFT of (0,0)->(w,0)


def test_ids_are_contiguous_in_emission_order():
    _i, result = electrical(two_rooms_shared_wall())
    assert [d.id for d in result.devices] == [
        f"E-{i:03d}" for i in range(1, len(result.devices) + 1)
    ]
    rules = [d.rule for d in result.devices]
    assert rules == sorted(
        rules, key=["E-1", "corridor", "laundry", "E-2", "E-2-basin", "appliance", "E-3"].index
    )


def test_appliance_receptacles_and_240v():
    _i, result = electrical(
        kitchen(with_casework=False), {"panel": [50.0, 1800.0], "slab_to_slab_mm": 3000.0}
    )
    appliance = {d.source: d for d in result.devices if d.rule == "appliance"}
    assert set(appliance) == {
        "F-002",
        "F-003",
    }  # dishwasher 120 V, range 240 V (sink has no electrical)
    assert appliance["F-002"].kind == "gfci"  # on the derived counter wall -> area rule
    assert appliance["F-003"].kind == "receptacle_240" and appliance["F-003"].circuit == "240V"
    assert any(i.code == "electrical_240" and i.refs == ["F-003"] for i in result.items)
    assert any(f.id == "F-001" for f in _i.fixtures)  # sink stays a plumbing fixture only
