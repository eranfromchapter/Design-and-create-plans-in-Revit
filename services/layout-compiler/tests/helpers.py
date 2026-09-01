"""Layout builders for the validator/compiler tests (pytest puts this dir on
sys.path, same pattern as the other services). All synthetic."""

from __future__ import annotations

from typing import Any

PROJECT_ID = "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01"
NEW_WALL = "CHPT_Partition_92mm_PLACEHOLDER"
NEW_DOOR = "CHPT_Door_Single_PLACEHOLDER"
NEW_WINDOW = "CHPT_Window_DoubleHung_PLACEHOLDER"


def wall(i: int, start: list[float], end: list[float], **over: Any) -> dict[str, Any]:
    return {
        "id": f"W-{i:03d}",
        "start": start,
        "end": end,
        "revit_type": NEW_WALL,
        "height": 2700,
        "source": "generated",
        **over,
    }


def door(i: int, host: str, offset: float, **over: Any) -> dict[str, Any]:
    return {
        "id": f"D-{i:03d}",
        "host_wall_id": host,
        "offset": offset,
        "width": 915,
        "height": 2040,
        "revit_type": NEW_DOOR,
        "swing": "L",
        **over,
    }


def room(i: int, boundary: list[list[float]], wall_ids: list[str], **over: Any) -> dict[str, Any]:
    return {
        "id": f"R-{i:03d}",
        "name": f"Room {i}",
        "program": "living",
        "boundary": boundary,
        "boundary_wall_ids": wall_ids,
        **over,
    }


def make_layout(**over: Any) -> dict[str, Any]:
    """A minimal VALID phase="new" layout: one 4000x3000 room bounded by four
    generated walls, one door on the south wall."""
    walls = [
        wall(1, [0, 0], [4000, 0]),
        wall(2, [4000, 0], [4000, 3000]),
        wall(3, [4000, 3000], [0, 3000]),
        wall(4, [0, 3000], [0, 0]),
    ]
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
        "doors": [door(1, "W-001", 2000)],
        "windows": [],
        "rooms": [room(1, [[0, 0], [4000, 0], [4000, 3000], [0, 3000]], [w["id"] for w in walls])],
        "furniture": [],
        "constraints": {},
    }
    layout.update(over)
    return layout
