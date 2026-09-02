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


def kitchen(with_casework: bool) -> dict[str, Any]:
    """6000x3600 kitchen; sink + dishwasher on W-001 (south), range further along it.
    With casework: one is_counter run 600..3600 on W-001."""
    walls = [
        wall(1, [0, 0], [6000, 0]),
        wall(2, [6000, 0], [6000, 3600]),
        wall(3, [6000, 3600], [0, 3600]),
        wall(4, [0, 3600], [0, 0]),
    ]
    rooms = [
        room(
            1,
            [[0, 0], [6000, 0], [6000, 3600], [0, 3600]],
            ["W-001", "W-002", "W-003", "W-004"],
            program="kitchen",
        )
    ]
    placed = [
        fixture(1, "R-001", "kitchen_sink", [1500.0, 346.0]),
        fixture(2, "R-001", "dishwasher", [2250.0, 346.0]),
        fixture(3, "R-001", "range", [4000.0, 376.0]),
    ]
    layout = assemble(walls, [door(1, "W-003", 3000)], rooms, placed)
    if with_casework:
        layout["casework"] = [
            {
                "id": "K-001",
                "host_wall_id": "W-001",
                "offset": 600.0,
                "length": 3000.0,
                "depth": 600.0,
                "height": 900.0,
                "is_counter": True,
                "revit_family": "CHPT_Base_PLACEHOLDER",
                "revit_type": "Base_600_PLACEHOLDER",
            }
        ]
    return layout


def two_rooms_shared_wall(
    width: float = 3000.0, door_spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    """North room R-001 (y 0..3000) and south room R-002 (y -3000..0) share W-001
    (0,0)->(width,0); optional door on W-001 (offset/width/swing/flip_facing)."""
    walls = [
        wall(1, [0, 0], [width, 0]),
        wall(2, [width, 0], [width, 3000]),
        wall(3, [width, 3000], [0, 3000]),
        wall(4, [0, 3000], [0, 0]),
        wall(5, [width, 0], [width, -3000]),
        wall(6, [width, -3000], [0, -3000]),
        wall(7, [0, -3000], [0, 0]),
    ]
    rooms = [
        room(
            1,
            [[0, 0], [width, 0], [width, 3000], [0, 3000]],
            ["W-001", "W-002", "W-003", "W-004"],
            program="living",
        ),
        room(
            2,
            [[0, -3000], [width, -3000], [width, 0], [0, 0]],
            ["W-006", "W-005", "W-001", "W-007"],
            program="living",
        ),
    ]
    doors = [door(9, "W-003", width / 2), door(8, "W-006", width / 2)]
    if door_spec is not None:
        doors.append(
            door(
                1,
                "W-001",
                door_spec["offset"],
                **{k: v for k, v in door_spec.items() if k != "offset"},
            )
        )
    return assemble(walls, doors, rooms, [])


_GOLDEN_CHAIN: dict[str, Any] = {}


def golden_chain() -> dict[str, Any]:
    """Compile + furnish the golden 2BR through the recorded fixtures once per test
    session: {brief, commit0, commit1_layout, commit1_ops, furnished, interior_ops,
    placer_wall_ids}."""
    if not _GOLDEN_CHAIN:
        import json

        from layout_compiler.compile import CompileOptions, compile_layout
        from layout_compiler.fixtures import FixtureLLM
        from layout_compiler.furnish import FurnishOptions, furnish_layout
        from layout_compiler.golden_4br import REPO_ROOT, frozen_layout
        from layout_compiler.interior_fixtures import InteriorFixtureLLM

        brief = json.loads(
            (REPO_ROOT / "fixtures" / "briefs" / "2br_golden_brief.json").read_text()
        )
        brief["meta"]["confirmed_by_client"] = True
        project = brief["meta"]["project_id"]
        compiled = compile_layout(
            brief, frozen_layout(), CompileOptions(project_id=project), FixtureLLM()
        )
        furnished = furnish_layout(
            brief,
            frozen_layout(),
            compiled["layout"],
            compiled["ops"],
            FurnishOptions(project_id=project),
            InteriorFixtureLLM(),
        )
        _GOLDEN_CHAIN.update(
            brief=brief,
            commit0=frozen_layout(),
            commit1_layout=compiled["layout"],
            commit1_ops=compiled["ops"],
            furnished=furnished["layout"],
            interior_ops=furnished["ops"],
            placer_wall_ids={
                d["item_id"]: d["wall_id"]
                for d in furnished["diagnostics"]["items"]
                if d.get("wall_id")
            },
        )
    return _GOLDEN_CHAIN


GOLDEN_CONFIRMATIONS = {"panel": [8050.0, 5200.0], "slab_to_slab_mm": 3000.0}


_GOLDEN_PLAN: dict[str, Any] = {}


def golden_plan() -> dict[str, Any]:
    """plan_mep on the golden chain with GOLDEN_CONFIRMATIONS, once per session
    (callers deep-copy before mutating)."""
    if not _GOLDEN_PLAN:
        from layout_compiler.mep.plan import MepOptions, plan_mep

        g = golden_chain()
        _GOLDEN_PLAN.update(
            plan_mep(
                g["commit0"],
                g["commit1_layout"],
                g["commit1_ops"],
                g["interior_ops"],
                g["furnished"],
                g["placer_wall_ids"],
                GOLDEN_CONFIRMATIONS,
                MepOptions(project_id=g["brief"]["meta"]["project_id"]),
            )
        )
    return _GOLDEN_PLAN
