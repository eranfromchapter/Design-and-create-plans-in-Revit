"""The Phase 5 golden furniture emission: 20 hand-authored proposals for the
golden 4BR plan (SI-11 — synthetic). Centers are HINTS; the deterministic
placer computes legal positions, and scripts/gen_golden_furniture.py (which
runs the REAL placer + the full validator) is the sole source of golden truth.

Expected outcome (adversarially verified in the design pass, re-verified by
the generator): 18 placed, 2 unplaced —
- F-013 (Bath 2 lav): no legal position beside the wc at its 500mm clearance
  in the 1200mm-wide bath -> REVIEW demo #1;
- F-020 (laundry washer stack): the frozen 1200x1200 laundry plus D-011's
  in-room swing arc admits nothing deeper than ~300mm -> REVIEW demo #2.
Bath 1 gets wc+lav only (wc+lav+shower needs a 3450mm run > the 3175mm wall).
The washer/dryer STACK is ONE kind=washer item (Phase 6 never sees 'dryer')."""

from __future__ import annotations

from typing import Any

# room_id -> [(id, kind, family, type, center hint, fixture_units, hookups)]
PROPOSALS: list[tuple[str, str, str, str, str, list[float], float | None, list[str] | None]] = [
    (
        "R-001",
        "F-001",
        "bed",
        "CHPT_Bed_PLACEHOLDER",
        "Queen_1524x2032_PLACEHOLDER",
        [1800.0, 1166.0],
        None,
        None,
    ),
    (
        "R-001",
        "F-002",
        "wardrobe",
        "CHPT_Wardrobe_PLACEHOLDER",
        "Wardrobe_1200x600_PLACEHOLDER",
        [1800.0, 3479.0],
        None,
        None,
    ),
    (
        "R-001",
        "F-003",
        "desk",
        "CHPT_Desk_PLACEHOLDER",
        "Desk_1200x600_PLACEHOLDER",
        [425.0, 1900.0],
        None,
        None,
    ),
    (
        "R-002",
        "F-004",
        "bed",
        "CHPT_Bed_PLACEHOLDER",
        "Double_1372x1905_PLACEHOLDER",
        [2836.0, 6900.0],
        None,
        None,
    ),
    (
        "R-002",
        "F-005",
        "wardrobe",
        "CHPT_Wardrobe_PLACEHOLDER",
        "Wardrobe_1000x600_PLACEHOLDER",
        [1500.0, 6300.0],
        None,
        None,
    ),
    (
        "R-003",
        "F-006",
        "wc",
        "CHPT_WC_PLACEHOLDER",
        "WC_400x700_PLACEHOLDER",
        [600.0, 4225.0],
        4.0,
        ["sanitary", "supply_c", "vent"],
    ),
    (
        "R-003",
        "F-007",
        "lav",
        "CHPT_Lav_PLACEHOLDER",
        "Lav_500x450_PLACEHOLDER",
        [600.0, 6700.0],
        1.0,
        ["sanitary", "supply_h", "supply_c", "vent"],
    ),
    (
        "R-004",
        "F-008",
        "bed",
        "CHPT_Bed_PLACEHOLDER",
        "Twin_991x1905_PLACEHOLDER",
        [5204.5, 6900.0],
        None,
        None,
    ),
    (
        "R-004",
        "F-009",
        "table",
        "CHPT_Nightstand_PLACEHOLDER",
        "Nightstand_450x450_PLACEHOLDER",
        [3875.0, 6750.0],
        None,
        None,
    ),
    (
        "R-005",
        "F-010",
        "bed",
        "CHPT_Bed_PLACEHOLDER",
        "Twin_991x1905_PLACEHOLDER",
        [6241.5, 6000.0],
        None,
        None,
    ),
    (
        "R-005",
        "F-011",
        "table",
        "CHPT_Nightstand_PLACEHOLDER",
        "Nightstand_450x450_PLACEHOLDER",
        [7850.0, 6700.0],
        None,
        None,
    ),
    (
        "R-007",
        "F-012",
        "wc",
        "CHPT_WC_PLACEHOLDER",
        "WC_400x700_PLACEHOLDER",
        [10800.0, 5026.0],
        4.0,
        ["sanitary", "supply_c", "vent"],
    ),
    (
        "R-007",
        "F-013",
        "lav",
        "CHPT_Lav_PLACEHOLDER",
        "Lav_500x450_PLACEHOLDER",
        [10800.0, 6700.0],
        1.0,
        ["sanitary", "supply_h", "supply_c", "vent"],
    ),
    (
        "R-008",
        "F-014",
        "sofa",
        "CHPT_Sofa_PLACEHOLDER",
        "Sofa_2100x900_PLACEHOLDER",
        [10800.0, 2250.0],
        None,
        None,
    ),
    (
        "R-008",
        "F-015",
        "table",
        "CHPT_DiningTable_PLACEHOLDER",
        "Dining_900x1800_PLACEHOLDER",
        [9425.0, 1900.0],
        None,
        None,
    ),
    (
        "R-009",
        "F-016",
        "refrigerator",
        "CHPT_Refrigerator_PLACEHOLDER",
        "Fridge_750x750_PLACEHOLDER",
        [3750.0, 1800.0],
        None,
        ["electrical_120"],
    ),
    (
        "R-009",
        "F-017",
        "kitchen_sink",
        "CHPT_KitchenSink_PLACEHOLDER",
        "Sink_900x600_PLACEHOLDER",
        [6110.0, 450.0],
        2.0,
        ["sanitary", "supply_h", "supply_c", "vent"],
    ),
    (
        "R-009",
        "F-018",
        "dishwasher",
        "CHPT_Dishwasher_PLACEHOLDER",
        "DW_600x600_PLACEHOLDER",
        [6860.0, 450.0],
        2.0,
        ["sanitary", "supply_h", "electrical_120"],
    ),
    (
        "R-009",
        "F-019",
        "range",
        "CHPT_Range_PLACEHOLDER",
        "Range_762x660_PLACEHOLDER",
        [7541.0, 480.0],
        None,
        ["electrical_240"],
    ),
    (
        "R-011",
        "F-020",
        "washer",
        "CHPT_WasherDryerStack_PLACEHOLDER",
        "Stack_600x600_PLACEHOLDER",
        [4200.0, 600.0],
        2.0,
        ["sanitary", "supply_h", "supply_c", "electrical_120", "electrical_240"],
    ),
]

EXPECTED_UNPLACED = ["F-013", "F-020"]


def emission() -> dict[str, Any]:
    """The emit_furniture tool input: contract furniture entries, room order."""
    from layout_compiler.catalogs import family_types

    entries: dict[str, list[dict[str, Any]]] = {}
    for room_id, item_id, kind, family, revit_type, center, fu, hookups in PROPOSALS:
        spec = family_types()[(family, revit_type)]
        item: dict[str, Any] = {
            "id": item_id,
            "kind": kind,
            "revit_family": family,
            "revit_type": revit_type,
            "center": center,
            "rotation_deg": 0.0,
            "footprint": list(spec["footprint_mm"]),
        }
        if fu is not None:
            item["fixture_units"] = fu
        if hookups is not None:
            item["hookups"] = hookups
        entries.setdefault(room_id, []).append(item)
    return {
        "furniture": [
            {"room_id": room_id, "items": entries[room_id]} for room_id in sorted(entries)
        ]
    }
