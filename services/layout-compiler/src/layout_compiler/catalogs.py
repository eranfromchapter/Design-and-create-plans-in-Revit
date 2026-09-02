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
    """The closed vocabulary injected verbatim into the compiler prompt (D1).
    Deliberately the whole catalog file (families included) — documented at the
    Phase 5 gate."""
    return json.dumps(_load("new_construction_types.json"), indent=2)


@cache
def new_families() -> dict[str, dict]:
    """revit_family -> catalog entry (Phase 5 furniture vocabulary, D1)."""
    return {f["revit_family"]: f for f in _load("new_construction_types.json")["families"]}


@cache
def family_types() -> dict[tuple[str, str], dict]:
    """(revit_family, revit_type) -> {footprint_mm, clearance_front_mm, kinds,
    wall_seeking_default}. The placer stamps these onto every item — the LLM
    proposes WHAT goes where, never geometry."""
    out: dict[tuple[str, str], dict] = {}
    for family in _load("new_construction_types.json")["families"]:
        for entry in family["types"]:
            out[(family["revit_family"], entry["revit_type"])] = {
                "footprint_mm": [float(v) for v in entry["footprint_mm"]],
                "clearance_front_mm": float(entry.get("clearance_front_mm", 0)),
                "kinds": tuple(family["kinds"]),
                "wall_seeking_default": bool(family.get("wall_seeking_default", True)),
            }
    return out


@cache
def pocket_door_types() -> frozenset[str]:
    """Pocket doors have no swing leaf — they emit no swing arc (Phase 5 pin).
    Union over BOTH catalogs: kept source="scan" doors resolve via the as-built
    vocabulary, and an as-built pocket door must never grow a phantom arc.
    (Name-based detection is a stopgap — an explicit leafless flag on catalog
    door entries is a flagged gate ask, since catalogs are human-owned.)"""
    return frozenset(
        d["revit_type"]
        for d in [
            *_load("new_construction_types.json")["doors"],
            *_load("asbuilt_types.json")["doors"],
        ]
        if "pocket" in d["revit_type"].lower()
    )


@cache
def plumbing_fixtures() -> dict[str, dict]:
    """kind -> {fixture_units, hookups} from catalogs/plumbing.json — the
    authoritative MEP table (Part G P-1..P-4). Phase 5 overwrites LLM-proposed
    fixture_units/hookups from here so the Phase 6 seed is catalog-owned."""
    fixtures = _load("plumbing.json")["fixtures"]
    return {
        kind: {
            "fixture_units": float(entry["fixture_units"]),
            "hookups": list(entry["hookups"]),
        }
        for kind, entry in fixtures.items()
    }


@cache
def families_vocabulary_block() -> str:
    """The closed furniture vocabulary injected verbatim into the furnish prompt."""
    return json.dumps(_load("new_construction_types.json")["families"], indent=2)
