"""place_family op emission for the interior branch delta (Phase 5).

One op per PLACED item, F-id-sorted, args exactly the registry's seven keys;
`level` comes from the layout meta (never a hardcoded default). Every op is
validated against the registry args_schema before return — the gateway
re-validates before signing, and this module's output must always pass.

Unplaced items produce NO op: their full proposals (hookups included) ride in
the review content's `unplaced` list and are EXCLUDED from Commit #2."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

import jsonschema

from layout_compiler.catalogs import CONTRACTS_DIR


@cache
def _place_family_schema() -> dict[str, Any]:
    registry = json.loads((CONTRACTS_DIR / "ops" / "registry.json").read_text())
    return registry["ops"]["place_family"]["args_schema"]


def furniture_ops(furniture: list[dict[str, Any]], level: str) -> list[dict[str, Any]]:
    """furniture: layout-shaped entries [{room_id, items}] of PLACED items."""
    items = sorted((item for entry in furniture for item in entry["items"]), key=lambda i: i["id"])
    ops: list[dict[str, Any]] = []
    for item in items:
        args = {
            "id": item["id"],
            "revit_family": item["revit_family"],
            "revit_type": item["revit_type"],
            "center": [round(float(item["center"][0]), 1), round(float(item["center"][1]), 1)],
            "rotation_deg": round(float(item["rotation_deg"]) % 360.0, 1) % 360.0,
            "footprint": [float(v) for v in item["footprint"]],
            "level": level,
        }
        jsonschema.validate(args, _place_family_schema())
        ops.append({"op": "place_family", "args": args})
    return ops
