"""Catalog vocabulary (human-owned, D1): generated elements must use
new_construction_types.json; scan walls resolve via asbuilt_types.json. The
validator AND revit-sim both enforce membership, so CI mirrors the live-Revit
failure mode."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "packages" / "contracts"


@cache
def _load(name: str) -> dict:
    return json.loads((CONTRACTS_DIR / "catalogs" / name).read_text())


@cache
def new_wall_types() -> frozenset[str]:
    return frozenset(t["revit_type"] for t in _load("new_construction_types.json")["walls"])


@cache
def asbuilt_wall_types() -> frozenset[str]:
    return frozenset(t["revit_type"] for t in _load("asbuilt_types.json")["types"])


@cache
def wall_thickness_mm() -> dict[str, float]:
    """revit_type -> thickness, both catalogs (generated walls have no
    as_built_thickness; boundary-consistency needs t/2)."""
    out: dict[str, float] = {}
    for t in _load("asbuilt_types.json")["types"]:
        out[t["revit_type"]] = float(t["thickness_mm"])
    for t in _load("new_construction_types.json")["walls"]:
        out[t["revit_type"]] = float(t["thickness_mm"])
    return out


@cache
def door_types() -> frozenset[str]:
    """Union: openings carry no `source` field in the schema, so membership is
    checked against both vocabularies (the diff pins kept scan openings by id)."""
    return frozenset(
        t["revit_type"]
        for t in [
            *_load("new_construction_types.json")["doors"],
            *_load("asbuilt_types.json")["doors"],
        ]
    )


@cache
def window_types() -> frozenset[str]:
    return frozenset(
        t["revit_type"]
        for t in [
            *_load("new_construction_types.json")["windows"],
            *_load("asbuilt_types.json")["windows"],
        ]
    )


@cache
def new_vocabulary_block() -> str:
    """The closed vocabulary injected verbatim into the compiler prompt (D1)."""
    return json.dumps(_load("new_construction_types.json"), indent=2)
