"""Synthetic apartments for the Phase 6 MEP tests (mm). Two adjoining bathrooms share
the 152 mm wet wall W-005; every fixture carries its catalog semantics the way the
Phase 5 furnish pass stamps them (kind, fixture_units, hookups)."""

from __future__ import annotations

from typing import Any

from helpers import PROJECT_ID, door, room, wall

WET = "CHPT_Partition_Wet_152mm_PLACEHOLDER"


def fixture(i: int, room_id: str, kind: str, center: list[float], **over: Any) -> dict[str, Any]:
    spec = {
        "wc": (
            "CHPT_WC_PLACEHOLDER",
            "WC_400x700_PLACEHOLDER",
            [400.0, 700.0],
            4.0,
            ["sanitary", "supply_c", "vent"],
        ),
        "lav": (
            "CHPT_Lav_PLACEHOLDER",
            "Lav_500x450_PLACEHOLDER",
            [500.0, 450.0],
            1.0,
            ["sanitary", "supply_h", "supply_c", "vent"],
        ),
        "shower": (
            "CHPT_Shower_PLACEHOLDER",
            "Shower_900x900_PLACEHOLDER",
            [900.0, 900.0],
            2.0,
            ["sanitary", "supply_h", "supply_c", "vent"],
        ),
        "kitchen_sink": (
            "CHPT_Sink_PLACEHOLDER",
            "Sink_900x600_PLACEHOLDER",
            [900.0, 600.0],
            2.0,
            ["sanitary", "supply_h", "supply_c", "vent"],
        ),
        "dishwasher": (
            "CHPT_Dishwasher_PLACEHOLDER",
            "DW_600x600_PLACEHOLDER",
            [600.0, 600.0],
            2.0,
            ["sanitary", "supply_h", "electrical_120"],
        ),
        "range": (
            "CHPT_Range_PLACEHOLDER",
            "Range_762x660_PLACEHOLDER",
            [762.0, 660.0],
            None,
            ["electrical_240"],
        ),
        "bed": ("CHPT_Bed_PLACEHOLDER", "Twin_991x1905_PLACEHOLDER", [991.0, 1905.0], None, []),
    }[kind]
    family, rtype, footprint, fu, hookups = spec
    item: dict[str, Any] = {
        "id": f"F-{i:03d}",
        "kind": kind,
        "revit_family": family,
        "revit_type": rtype,
        "center": center,
        "rotation_deg": 0.0,
        "footprint": footprint,
        "hookups": hookups,
        "clearance_front": 0.0,
        "wall_seeking": True,
    }
    if fu is not None:
        item["fixture_units"] = fu
    item.update(over)
    return {"room_id": room_id, "item": item}


def assemble(walls, doors, rooms, placed, **over: Any) -> dict[str, Any]:
    furniture: dict[str, list[dict[str, Any]]] = {}
    for p in placed:
        furniture.setdefault(p["room_id"], []).append(p["item"])
    layout: dict[str, Any] = {
        "meta": {
            "project_id": PROJECT_ID,
            "level": "Level 1",
            "units": "mm",
            "origin": "revit_internal_origin",
            "schema_version": "2.3",
            "brief_version": 1,
            "phase": "new",
        },
        "walls": walls,
        "doors": doors,
        "windows": [],
        "rooms": rooms,
        "furniture": [{"room_id": r, "items": items} for r, items in sorted(furniture.items())],
        "constraints": {"circulation_min": 900},
    }
    layout.update(over)
    return layout


def two_baths(**over: Any) -> dict[str, Any]:
    """Bath A [0..2400]x[0..3000] and Bath B [2400..4800]x[0..3000] share W-005 (x=2400,
    wet 152). A: wc (4 FU) + lav (1 FU); B: wc (4 FU). Doors on the north walls."""
    walls = [
        wall(1, [0, 0], [2400, 0]),
        wall(5, [2400, 0], [2400, 3000], revit_type=WET, is_wet_wall=True),
        wall(3, [2400, 3000], [0, 3000]),
        wall(4, [0, 3000], [0, 0]),
        wall(2, [2400, 0], [4800, 0]),
        wall(6, [4800, 0], [4800, 3000]),
        wall(7, [4800, 3000], [2400, 3000]),
    ]
    rooms = [
        room(
            1,
            [[0, 0], [2400, 0], [2400, 3000], [0, 3000]],
            ["W-001", "W-005", "W-003", "W-004"],
            program="bathroom",
            wet_zone=True,
        ),
        room(
            2,
            [[2400, 0], [4800, 0], [4800, 3000], [2400, 3000]],
            ["W-002", "W-006", "W-007", "W-005"],
            program="bathroom",
            wet_zone=True,
        ),
    ]
    doors = [door(1, "W-003", 1200), door(2, "W-007", 1200)]
    placed = [
        # backs to W-005 (x=2400): rotation 90 puts the footprint depth along x, so the
        # centre sits t/2 + depth/2 from the centerline (76 + 350 = 426; lav 76 + 225)
        fixture(1, "R-001", "wc", [1974.0, 800.0], rotation_deg=90.0),
        fixture(2, "R-001", "lav", [2099.0, 2200.0], rotation_deg=90.0),
        fixture(3, "R-002", "wc", [2826.0, 800.0], rotation_deg=90.0),
    ]
    return assemble(walls, doors, rooms, placed, **over)


def commit0_for(layout: dict[str, Any], height: float = 2700.0) -> dict[str, Any]:
    return {**layout, "walls": [{**w, "height": height} for w in layout["walls"]]}


CONFIRMATIONS = {"panel": [50.0, 1500.0], "slab_to_slab_mm": 3000.0}
