"""MEP op emission (docs/PHASE6_DESIGN.md §3.4): create_pipe (stacks, then branch
segments) -> place_device (E order, with `face`) -> create_conduit (drops, then
trunk chains). Every op is validated against ops/registry.json args_schema before
it leaves the compiler; numbers are rounded to 0.1 mm; the pipe type comes from
catalogs/mep_types.json (placeholders until Eran's vocabulary lands)."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

import jsonschema

from layout_compiler.catalogs import CONTRACTS_DIR, mep_types
from layout_compiler.mep.constants import COORD_ROUND, E4_CONDUIT_DIAMETER_MM
from layout_compiler.mep.electrical import Device
from layout_compiler.mep.inputs import MepError, MepInputs
from layout_compiler.mep.plumbing import Segment, Stack


@cache
def _registry() -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / "ops" / "registry.json").read_text())


def validate_ops(ops: list[dict[str, Any]]) -> None:
    registry = _registry()["ops"]
    for op in ops:
        entry = registry.get(op["op"])
        if entry is None:
            raise MepError("mep_internal", f"unknown op {op['op']!r}")
        try:
            jsonschema.validate(op["args"], entry["args_schema"])
        except jsonschema.ValidationError as err:
            raise MepError(
                "mep_internal", f"{op['op']} {op['args'].get('id')}: {err.message}"
            ) from err


def _r(v: float) -> float:
    return round(float(v), COORD_ROUND)


def pipe_ops(
    stacks: list[Stack], segments: list[Segment], inputs: MepInputs
) -> list[dict[str, Any]]:
    pipe_type = mep_types()["pipe_types"]["sanitary"]
    level = inputs.layout["meta"]["level"]
    floor_z, ceiling_z = inputs.floor_z, inputs.ceiling_z
    h_plenum = inputs.h_plenum or 0.0
    ops: list[dict[str, Any]] = []
    for stack in stacks:
        sx, sy = _r(stack.xy[0]), _r(stack.xy[1])
        ops.append(
            {
                "op": "create_pipe",
                "args": {
                    "id": stack.id,
                    "system": "sanitary",
                    "pipe_type": pipe_type,
                    "level": level,
                    "path": [[sx, sy, _r(floor_z - h_plenum)], [sx, sy, _r(ceiling_z)]],
                    "diameter": float(stack.diameter),
                },
            }
        )
    for seg in segments:
        ops.append(
            {
                "op": "create_pipe",
                "args": {
                    "id": seg.id,
                    "system": "sanitary",
                    "pipe_type": pipe_type,
                    "level": level,
                    "path": [[_r(c) for c in seg.start], [_r(c) for c in seg.end]],
                    "diameter": float(seg.diameter),
                },
            }
        )
    return ops


def device_ops(devices: list[Device]) -> list[dict[str, Any]]:
    return [
        {
            "op": "place_device",
            "args": {
                "id": d.id,
                "kind": d.kind,
                "host_wall_id": d.host_wall_id,
                "offset": _r(d.offset),
                "height_afl": float(d.height_afl),
                "face": d.face,
            },
        }
        for d in devices
    ]


def conduit_ops(
    drops: list[dict[str, Any]], trunks: list[dict[str, Any]], inputs: MepInputs
) -> list[dict[str, Any]]:
    level = inputs.layout["meta"]["level"]
    return [
        {
            "op": "create_conduit",
            "args": {
                "id": run["id"],
                "level": level,
                "path": [[_r(x), _r(y), _r(z)] for x, y, z in run["path"]],
                "diameter": float(E4_CONDUIT_DIAMETER_MM),
            },
        }
        for run in [*drops, *trunks]
    ]
