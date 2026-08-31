"""Geometry spec for the canonical Lane A fixture: a synthetic ~75 m2 prewar 2BR
(PLAN.md Phase 2). SINGLE SOURCE OF TRUTH for fixtures/scans/2br_uws.dxf —
scripts/gen_fixture_dxf.py writes the DXF from this module and
tests/test_fixture_drift.py compares the committed file back against it
entity-wise (headers ignored: ezdxf stamps GUIDs/timestamps on every save).

All coordinates in mm ($INSUNITS=4). Synthetic only — no client data (SI-11).

Plan (centerline outline 11400 x 7000, party walls E/W = demising sides):

    N corridor wall (t=200)
  +--------------------------------------------+
  | BR2      |spine     KITCHEN    |skew        |
  |----------|   +--wet wall (t=150)  FOYER    |
  | BR1      |   BATH  |           |            |
  |          |   +--wet-block south wall (t=100)|
  |          |        LIVING ROOM               |
  +---------------~~~bay~~~--------------------+
    S facade (t=300) with curved bay return

Expected conversion (asserted across the pytest suite):
- 17 wall records: 2 party (t250) + 1 corridor (t200) + 2 facade straights (t300)
  + 7 curved-bay chords (t300, bulge +0.35 => R=1603.57mm, theta=77.16deg,
  sagitta-10 tessellation) + spine (t100) + divider (t100, 0.796deg off => snaps
  exactly horizontal to y=3825) + wet-block (t100) + wet wall (t150)
  + foyer wall (t100, 3.58deg off vertical => preserved + skew flag)
- 5 doors, 3 windows (all on straight walls), 6 informational room labels
- low-confidence list: 7 chords + 1 skew + 5 doors + 3 windows = 16 entries
"""

from __future__ import annotations

INSUNITS = 4  # mm

# LWPOLYLINE walls: (layer stays "WALLS"; width = const_width = wall thickness;
# points are (x, y, bulge) — bulge on a vertex curves the segment leaving it).
WALL_POLYLINES: list[dict] = [
    # W party wall (demising side)
    {"width": 250.0, "points": [(0.0, 0.0, 0.0), (0.0, 7000.0, 0.0)]},
    # E party wall (demising side)
    {"width": 250.0, "points": [(11400.0, 0.0, 0.0), (11400.0, 7000.0, 0.0)]},
    # N corridor wall
    {"width": 200.0, "points": [(0.0, 7000.0, 0.0), (11400.0, 7000.0, 0.0)]},
    # S facade with the curved bay return between x=8000 and x=10000:
    # bulge +0.35 (CCW) => mid-ordinate 350mm SOUTH of the chord (outward bow;
    # verified against ezdxf.math.bulge_to_arc — apex (9000, -350)).
    {
        "width": 300.0,
        "points": [
            (0.0, 0.0, 0.0),
            (8000.0, 0.0, 0.35),
            (10000.0, 0.0, 0.0),
            (11400.0, 0.0, 0.0),
        ],
    },
    # bedroom spine
    {"width": 100.0, "points": [(3600.0, 0.0, 0.0), (3600.0, 7000.0, 0.0)]},
    # bedroom divider — deliberately 0.796 deg off horizontal; must snap exactly
    {"width": 100.0, "points": [(0.0, 3800.0, 0.0), (3600.0, 3850.0, 0.0)]},
    # wet-block south wall
    {"width": 100.0, "points": [(3600.0, 4600.0, 0.0), (7000.0, 4600.0, 0.0)]},
    # wet wall, kitchen/bath back-to-back
    {"width": 150.0, "points": [(5300.0, 4600.0, 0.0), (5300.0, 7000.0, 0.0)]},
    # foyer wall — deliberately 3.58 deg off vertical; must be preserved + flagged
    {"width": 100.0, "points": [(7000.0, 4600.0, 0.0), (7150.0, 7000.0, 0.0)]},
]

# LINE openings lying along their host wall, spanning the opening width.
DOOR_LINES: list[tuple[tuple[float, float], tuple[float, float]]] = [
    ((8142.5, 7000.0), (9057.5, 7000.0)),  # entry, N corridor wall, w=915
    ((3600.0, 1619.0), (3600.0, 2381.0)),  # BR1, spine, w=762
    ((3600.0, 3856.5), (3600.0, 4567.5)),  # BR2, spine, w=711
    ((4094.5, 4600.0), (4805.5, 4600.0)),  # bath, wet-block wall, w=711
    ((5692.5, 4600.0), (6607.5, 4600.0)),  # kitchen, wet-block wall, w=915
]

WINDOW_LINES: list[tuple[tuple[float, float], tuple[float, float]]] = [
    ((1266.5, 0.0), (2333.5, 0.0)),  # facade, w=1067
    ((6266.5, 0.0), (7333.5, 0.0)),  # facade, w=1067
    ((10242.5, 0.0), (11157.5, 0.0)),  # facade E of bay, w=915
]

# TEXT room labels — informational in v1 (rooms=[] at Commit #0), surfaced in the
# review payload so the human sees what the scan thinks the rooms are.
ROOM_LABELS: list[tuple[str, tuple[float, float]]] = [
    ("BEDROOM 1", (1800.0, 1900.0)),
    ("BEDROOM 2", (1800.0, 5400.0)),
    ("BATH", (4450.0, 5800.0)),
    ("KITCHEN", (6150.0, 5800.0)),
    ("LIVING ROOM", (7500.0, 2300.0)),
    ("FOYER", (9200.0, 5800.0)),
]
