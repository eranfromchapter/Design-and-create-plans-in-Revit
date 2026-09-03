"""E-2 (Part G): counter circuit a = 610 / S = 1220 at 1150 AFF on casework counter
walls (and the derived fallback), the <= 914 mm basin rule, and the area-based GFCI
rule (no plain receptacle on a counter wall or in a bathroom/powder/laundry)."""

from __future__ import annotations

from mep_helpers import CONFIRMATIONS, commit0_for, kitchen, two_baths

from layout_compiler.mep.electrical import plan_electrical
from layout_compiler.mep.inputs import offset_of, resolve_inputs

KITCHEN_CONF = {"panel": [50.0, 1800.0], "slab_to_slab_mm": 3000.0}


def electrical(layout, confirmations):
    inputs = resolve_inputs(layout, commit0_for(layout), confirmations)
    return inputs, plan_electrical(inputs)


def test_e2_counter_circuit_from_casework():
    _i, result = electrical(kitchen(with_casework=True), KITCHEN_CONF)
    counter = sorted(d.offset for d in result.devices if d.rule == "E-2")
    # run 600..3600 (L = 3000): N = 3 -> 610, 1500, 2390 from the run start
    assert counter == [1210.0, 2100.0, 2990.0]
    assert counter[0] - 600.0 <= 610.0 + 1.0 and 3600.0 - counter[-1] <= 610.0 + 1.0
    assert all(b - a <= 1220.0 + 1.0 for a, b in zip(counter, counter[1:], strict=False))
    devices = [d for d in result.devices if d.rule == "E-2"]
    assert all(
        d.kind == "gfci" and d.height_afl == 1150.0 and d.host_wall_id == "W-001" for d in devices
    )


def test_e2_counter_circuit_from_the_derived_fallback():
    inputs, result = electrical(kitchen(with_casework=False), KITCHEN_CONF)
    assert inputs.counter_runs[("R-001", "W-001")] == [(450.0, 3150.0)]
    counter = sorted(d.offset for d in result.devices if d.rule == "E-2")
    assert counter and all(450.0 <= o <= 3150.0 for o in counter)
    assert all(b - a <= 1220.0 + 1.0 for a, b in zip(counter, counter[1:], strict=False))


def test_e2_bathroom_gfci_within_914_of_the_basin():
    inputs, result = electrical(two_baths(), CONFIRMATIONS)
    lav = next(f for f in inputs.fixtures if f.kind == "lav")
    (gfci,) = [d for d in result.devices if d.rule == "E-2-basin"]
    foot = offset_of(lav.center, inputs.walls[lav.host_wall_id])
    assert gfci.host_wall_id == lav.host_wall_id and gfci.source == lav.id
    assert 300.0 - 1e-9 <= abs(gfci.offset - foot) <= 914.0 + 1.0
    assert gfci.kind == "gfci" and gfci.height_afl == 1150.0 and gfci.room_id == "R-001"


def test_bath_gfci_unplaceable_when_no_legal_position():
    layout = two_baths()
    # a door on W-005 covers every position 300..900 on either side of the lav's foot (2200)
    layout["doors"].append(
        {
            **layout["doors"][0],
            "id": "D-003",
            "host_wall_id": "W-005",
            "offset": 2200.0,
            "width": 2000.0,
        }
    )
    _i, result = electrical(layout, CONFIRMATIONS)
    assert [d for d in result.devices if d.rule == "E-2-basin"] == []
    assert any(i.code == "bath_gfci_unplaceable" and i.refs == ["F-002"] for i in result.items)


def test_gfci_area_rule():
    inputs, result = electrical(kitchen(with_casework=False), KITCHEN_CONF)
    for d in result.devices:
        if d.kind == "switch":
            continue
        on_counter_wall = d.host_wall_id in inputs.counter_walls.get(d.room_id, [])
        if on_counter_wall:
            assert d.kind in ("gfci", "receptacle_240"), d
        elif d.rule == "E-1":
            assert d.kind == "receptacle", d
    _i2, baths = electrical(two_baths(), CONFIRMATIONS)
    assert all(d.kind in ("gfci", "switch") for d in baths.devices)
