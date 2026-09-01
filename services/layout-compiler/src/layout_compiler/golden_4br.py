"""The Phase 4 golden emission: the hand-authored phase="new" 4BR plan for the
2BR UWS fixture (SI-11 — synthetic, geometry verified against
fixtures/layouts/2br_golden.json). scripts/gen_golden_new_layout.py writes it
to fixtures/llm/layout_golden_4br.json; test_fixture_drift pins the bytes and
test_acceptance runs the full validator + Part G diff against the real frozen
Commit #0.

Plan summary (brief: 4 bedrooms, open kitchen/dining, 2 baths, laundry):
- keeps 15 scan walls verbatim (envelope, spine W-005, W-006, divider W-003,
  the 7 curved-bay chords); demolishes W-007, W-008 (old BR2 interior) and
  doors D-002, D-005 by phasing
- 10 new walls: BR3/BR4 split W-018, foyer walls W-019/W-020/W-021, kitchen
  walls W-022/W-024, wet walls W-023 (bath2), W-025 (bath1), W-026/W-027
  (laundry closet)
- 8 new doors (2 pocket doors for the open kitchen), 11 rooms
- every clearance >= 31mm from the validator's thresholds (D-003's span vs
  W-003/W-006 is the tightest)"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]

P92 = "CHPT_Partition_92mm_PLACEHOLDER"
W152 = "CHPT_Partition_Wet_152mm_PLACEHOLDER"
DOOR = "CHPT_Door_Single_PLACEHOLDER"
POCKET = "CHPT_Door_Pocket_PLACEHOLDER"

KEPT_WALLS = [f"W-{i:03d}" for i in (*range(1, 7), *range(9, 18))]  # not W-007, W-008
KEPT_DOORS = ["D-001", "D-003", "D-004"]
KEPT_WINDOWS = ["N-001", "N-002", "N-003"]
DEMOLISHED = ["D-002", "D-005", "W-007", "W-008"]

# id, start, end, revit_type, wet
NEW_WALLS: list[tuple[str, list[float], list[float], str, bool]] = [
    ("W-018", [5700.0, 4600.0], [5700.0, 7000.0], P92, False),  # BR3 / BR4
    ("W-019", [8000.0, 4600.0], [8000.0, 7000.0], P92, False),  # BR4 / foyer
    ("W-020", [7000.0, 4600.0], [8000.0, 4600.0], P92, False),  # closes W-006's line east
    ("W-021", [8000.0, 4600.0], [11400.0, 4600.0], P92, False),  # foyer+bath2 / living
    ("W-022", [8000.0, 0.0], [8000.0, 4600.0], P92, False),  # kitchen / living
    ("W-023", [10200.0, 4600.0], [10200.0, 7000.0], W152, True),  # foyer / bath2
    ("W-024", [3600.0, 2800.0], [8000.0, 2800.0], P92, False),  # kitchen / hall
    ("W-025", [1200.0, 3825.0], [1200.0, 7000.0], W152, True),  # bath1 / BR2
    ("W-026", [4800.0, 0.0], [4800.0, 1200.0], W152, True),  # laundry east
    ("W-027", [3600.0, 1200.0], [4800.0, 1200.0], W152, True),  # laundry north
]

# id, host, offset, width, revit_type
NEW_DOORS: list[tuple[str, str, float, float, str]] = [
    ("D-006", "W-024", 3200.0, 1700.0, POCKET),  # kitchen <-> hall
    ("D-007", "W-021", 1500.0, 915.0, DOOR),  # foyer <-> living
    ("D-008", "W-022", 1200.0, 1700.0, POCKET),  # kitchen <-> living (open feel)
    ("D-009", "W-025", 1600.0, 711.0, DOOR),  # BR2 <-> bath1 (ensuite)
    ("D-010", "W-023", 1200.0, 711.0, DOOR),  # foyer <-> bath2
    ("D-011", "W-026", 600.0, 711.0, DOOR),  # kitchen <-> laundry
    ("D-012", "W-005", 3300.0, 762.0, DOOR),  # BR1 <-> hall (replaces D-002)
    ("D-013", "W-020", 500.0, 762.0, DOOR),  # hall <-> BR4
]

BAY = [
    [8258.1, -168.1],
    [8543.6, -283.7],
    [8846.0, -342.6],
    [9154.0, -342.6],
    [9456.4, -283.7],
    [9741.9, -168.1],
]

# id, name, program, wet, boundary, boundary_wall_ids
ROOMS: list[tuple[str, str, str, bool, list[list[float]], list[str]]] = [
    (
        "R-001",
        "Bedroom 1",
        "bedroom",
        False,
        [[0.0, 0.0], [3600.0, 0.0], [3600.0, 3825.0], [0.0, 3825.0]],
        ["W-001", "W-002", "W-005", "W-003"],
    ),
    (
        "R-002",
        "Bedroom 2",
        "bedroom",
        False,
        [[1200.0, 3825.0], [3600.0, 3825.0], [3600.0, 7000.0], [1200.0, 7000.0]],
        ["W-025", "W-003", "W-005", "W-004"],
    ),
    (
        "R-003",
        "Bath 1",
        "bathroom",
        True,
        [[0.0, 3825.0], [1200.0, 3825.0], [1200.0, 7000.0], [0.0, 7000.0]],
        ["W-001", "W-003", "W-025", "W-004"],
    ),
    (
        "R-004",
        "Bedroom 3",
        "bedroom",
        False,
        [[3600.0, 4600.0], [5700.0, 4600.0], [5700.0, 7000.0], [3600.0, 7000.0]],
        ["W-005", "W-006", "W-018", "W-004"],
    ),
    (
        "R-005",
        "Bedroom 4",
        "bedroom",
        False,
        [[5700.0, 4600.0], [8000.0, 4600.0], [8000.0, 7000.0], [5700.0, 7000.0]],
        ["W-018", "W-006", "W-020", "W-019", "W-004"],
    ),
    (
        "R-006",
        "Foyer",
        "corridor",
        False,
        [[8000.0, 4600.0], [10200.0, 4600.0], [10200.0, 7000.0], [8000.0, 7000.0]],
        ["W-019", "W-021", "W-023", "W-004"],
    ),
    (
        "R-007",
        "Bath 2",
        "bathroom",
        True,
        [[10200.0, 4600.0], [11400.0, 4600.0], [11400.0, 7000.0], [10200.0, 7000.0]],
        ["W-023", "W-021", "W-017", "W-004"],
    ),
    (
        "R-008",
        "Living Room",
        "living",
        False,
        [[8000.0, 4600.0], [8000.0, 0.0], *BAY, [10000.0, 0.0], [11400.0, 0.0], [11400.0, 4600.0]],
        [
            "W-022",
            "W-009",
            "W-010",
            "W-011",
            "W-012",
            "W-013",
            "W-014",
            "W-015",
            "W-016",
            "W-017",
            "W-021",
        ],
    ),
    (
        "R-009",
        "Kitchen / Dining (open)",
        "kitchen",
        False,
        [
            [4800.0, 0.0],
            [8000.0, 0.0],
            [8000.0, 2800.0],
            [3600.0, 2800.0],
            [3600.0, 1200.0],
            [4800.0, 1200.0],
        ],
        ["W-002", "W-022", "W-024", "W-005", "W-027", "W-026"],
    ),
    (
        "R-010",
        "Hall",
        "corridor",
        False,
        [[3600.0, 2800.0], [8000.0, 2800.0], [8000.0, 4600.0], [3600.0, 4600.0]],
        ["W-024", "W-022", "W-006", "W-020", "W-005"],
    ),
    (
        "R-011",
        "Laundry",
        "laundry",
        True,
        [[3600.0, 0.0], [4800.0, 0.0], [4800.0, 1200.0], [3600.0, 1200.0]],
        ["W-002", "W-026", "W-027", "W-005"],
    ),
]


def frozen_layout() -> dict[str, Any]:
    return json.loads((REPO_ROOT / "fixtures" / "layouts" / "2br_golden.json").read_text())


def emission() -> dict[str, Any]:
    """The emit_layout tool input: the new plan minus pipeline-owned meta.
    Kept scan elements are copied verbatim from the frozen fixture (Part G)."""
    frozen = frozen_layout()
    walls = [copy.deepcopy(w) for w in frozen["walls"] if w["id"] in KEPT_WALLS]
    for wall_id, start, end, revit_type, wet in NEW_WALLS:
        wall: dict[str, Any] = {
            "id": wall_id,
            "start": start,
            "end": end,
            "revit_type": revit_type,
            "height": 2700.0,
            "source": "generated",
        }
        if wet:
            wall["is_wet_wall"] = True
        walls.append(wall)

    doors = [copy.deepcopy(d) for d in frozen["doors"] if d["id"] in KEPT_DOORS]
    for door_id, host, offset, width, revit_type in NEW_DOORS:
        doors.append(
            {
                "id": door_id,
                "host_wall_id": host,
                "offset": offset,
                "width": width,
                "height": 2040.0,
                "revit_type": revit_type,
                "swing": "L",
            }
        )

    windows = [copy.deepcopy(w) for w in frozen["windows"] if w["id"] in KEPT_WINDOWS]

    rooms = []
    for room_id, name, program, wet, boundary, wall_ids in ROOMS:
        room: dict[str, Any] = {
            "id": room_id,
            "name": name,
            "program": program,
            "boundary": boundary,
            "boundary_wall_ids": wall_ids,
        }
        if wet:
            room["wet_zone"] = True
        rooms.append(room)

    return {
        "walls": walls,
        "doors": doors,
        "windows": windows,
        "rooms": rooms,
        "furniture": [],
        "constraints": {
            "circulation_min": 900,
            "style_tags": ["modern", "warm minimalism", "light wood"],
        },
    }
