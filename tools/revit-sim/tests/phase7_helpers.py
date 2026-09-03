"""Shared Phase 7 test model: a 4 x 3 m room with openings, families, a device, a pipe and
a conduit, built in any insertion order (the section/axon renderers must be canonical)."""

from __future__ import annotations

from typing import Any

from revit_sim.model import Catalogs, SimModel

CATALOGS = Catalogs.load()
WALL_TYPE = "CHPT_Partition_92mm_PLACEHOLDER"
PIPE_TYPE = "CHPT_Pipe_PVC_DWV_PLACEHOLDER"

WALLS = {
    1: ([0, 0], [4000, 0]),  # y = 0: BEHIND the cut (yc = 1500) -> omitted from the section
    2: ([4000, 0], [4000, 3000]),  # crosses the cut -> filled cut rect
    3: ([4000, 3000], [0, 3000]),  # at/beyond the cut -> elevation rect with openings
    4: ([0, 3000], [0, 0]),  # crosses the cut -> filled cut rect
}


def wall_args(i: int) -> dict[str, Any]:
    start, end = WALLS[i]
    return {
        "id": f"W-{i:03d}",
        "start": start,
        "end": end,
        "revit_type": WALL_TYPE,
        "height": 2700,
        "phase": "new",
    }


def door_args(i: int, host: str, offset: float) -> dict[str, Any]:
    return {
        "id": f"D-{i:03d}",
        "host_wall_id": host,
        "offset": offset,
        "revit_type": "CHPT_Door_Single_PLACEHOLDER",
        "width": 813,
        "height": 2032,
        "swing": "L",
    }


def family_args(
    i: int,
    family: str,
    ftype: str,
    center: list[float],
    footprint: list[float],
    rotation: float = 0.0,
) -> dict[str, Any]:
    return {
        "id": f"F-{i:03d}",
        "revit_family": family,
        "revit_type": ftype,
        "center": center,
        "rotation_deg": rotation,
        "footprint": footprint,
        "level": "L1",
    }


BED = ("CHPT_Bed_PLACEHOLDER", "Queen_1524x2032_PLACEHOLDER", [1524, 2032])
WC = ("CHPT_WC_PLACEHOLDER", "WC_400x700_PLACEHOLDER", [400, 700])


def build_room(
    wall_order: tuple[int, ...] = (1, 2, 3, 4),
    *,
    family_order: tuple[int, ...] = (1, 2),
    with_mep: bool = True,
) -> SimModel:
    model = SimModel()
    for i in wall_order:
        model.apply("create_wall", wall_args(i), CATALOGS)
    model.apply("create_door", door_args(1, "W-003", 1000), CATALOGS)  # elevation opening
    model.apply("create_door", door_args(2, "W-001", 2000), CATALOGS)  # behind the cut
    model.apply("create_door", door_args(3, "W-002", 1500), CATALOGS)  # ON the cut plane
    model.apply(
        "create_window",
        {
            "id": "N-001",
            "host_wall_id": "W-003",
            "offset": 3000,
            "sill_height": 900,
            "revit_type": "CHPT_Window_DoubleHung_PLACEHOLDER",
            "width": 1067,
            "height": 1400,
        },
        CATALOGS,
    )
    families = {
        1: family_args(1, BED[0], BED[1], [2000, 2000], BED[2]),  # bed: crosses the cut
        2: family_args(2, WC[0], WC[1], [1000, 500], WC[2]),  # wc: entirely behind the cut
    }
    for i in family_order:
        model.apply("place_family", families[i], CATALOGS)
    if with_mep:
        model.apply(
            "place_device",
            {
                "id": "E-001",
                "kind": "receptacle",
                "host_wall_id": "W-003",
                "offset": 500,
                "height_afl": 380,
                "face": "left",
            },
            CATALOGS,
        )
        model.apply(
            "create_pipe",
            {
                "id": "P-001",
                "system": "sanitary",
                "pipe_type": PIPE_TYPE,
                "level": "L1",
                "path": [[500, 2000, -300], [3500, 2000, -300]],
                "diameter": 76,
            },
            CATALOGS,
        )
        model.apply(
            "create_conduit",
            {
                "id": "Q-001",
                "level": "L1",
                "path": [[500, 2500, 2600], [3500, 2500, 2600]],
                "diameter": 21,
            },
            CATALOGS,
        )
    return model
