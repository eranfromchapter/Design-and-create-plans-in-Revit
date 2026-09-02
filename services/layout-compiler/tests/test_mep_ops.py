"""Op emission: every MEP op validates against ops/registry.json; pipes carry the
catalog pipe type and 0.1 mm-rounded 3D paths, stacks span floor − h_plenum ..
ceiling, devices carry the required `face`, conduits are drops + trunks at 2600."""

from __future__ import annotations

import pytest
from mep_helpers import CONFIRMATIONS, commit0_for, two_baths

from layout_compiler.mep.electrical import plan_electrical
from layout_compiler.mep.inputs import MepError, resolve_inputs
from layout_compiler.mep.ops import conduit_ops, device_ops, pipe_ops, validate_ops
from layout_compiler.mep.plumbing import plan_plumbing
from layout_compiler.mep.routing import route_home_runs


def full_mep():
    layout = two_baths()
    inputs = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS)
    plumbing = plan_plumbing(inputs)
    zones = [(s.wall_id, s.offset) for s in plumbing.stacks]
    electrical = plan_electrical(inputs, zones)
    routing = route_home_runs(inputs, electrical.devices, zones)
    ops = (
        pipe_ops(plumbing.stacks, plumbing.segments, inputs)
        + device_ops(electrical.devices)
        + conduit_ops(routing.drops, routing.trunks, inputs)
    )
    return inputs, plumbing, electrical, routing, ops


def test_every_emitted_op_is_registry_valid_and_ids_are_unique():
    _i, plumbing, electrical, routing, ops = full_mep()
    validate_ops(ops)
    ids = [op["args"]["id"] for op in ops]
    assert len(ids) == len(set(ids))
    assert [op["op"] for op in ops] == (
        ["create_pipe"] * (len(plumbing.stacks) + len(plumbing.segments))
        + ["place_device"] * len(electrical.devices)
        + ["create_conduit"] * (len(routing.drops) + len(routing.trunks))
    )


def test_pipe_ops_shapes():
    inputs, plumbing, _e, _r, ops = full_mep()
    stack_op = next(op for op in ops if op["args"]["id"] == plumbing.stacks[0].id)
    assert stack_op["args"]["pipe_type"] == "CHPT_Pipe_PVC_DWV_PLACEHOLDER"
    (x0, y0, z0), (x1, y1, z1) = stack_op["args"]["path"]
    assert (x0, y0) == (x1, y1) == tuple(round(c, 1) for c in plumbing.stacks[0].xy)
    assert (z0, z1) == (inputs.floor_z - inputs.h_plenum, inputs.ceiling_z)
    for seg in plumbing.segments:
        op = next(o for o in ops if o["args"]["id"] == seg.id)
        assert len(op["args"]["path"]) == 2 and op["args"]["diameter"] == seg.diameter
        assert all(c == round(c, 1) for pt in op["args"]["path"] for c in pt)


def test_device_and_conduit_ops_shapes():
    _i, _p, electrical, routing, ops = full_mep()
    for dev in electrical.devices:
        op = next(o for o in ops if o["args"]["id"] == dev.id)
        assert op["args"]["face"] in ("left", "right") and op["args"]["kind"] == dev.kind
        assert op["args"]["height_afl"] == dev.height_afl
    for drop in routing.drops:
        op = next(o for o in ops if o["args"]["id"] == drop["id"])
        assert op["args"]["path"][1][2] == 2600.0 and op["args"]["diameter"] == 21.0


def test_validate_ops_rejects_a_malformed_op():
    bad = [
        {
            "op": "place_device",
            "args": {
                "id": "E-001",
                "kind": "receptacle",
                "host_wall_id": "W-001",
                "offset": 100.0,
                "height_afl": 380.0,
            },
        }
    ]  # no face
    with pytest.raises(MepError) as err:
        validate_ops(bad)
    assert err.value.code == "mep_internal" and "face" in err.value.message
    with pytest.raises(MepError):
        validate_ops([{"op": "teleport", "args": {}}])
