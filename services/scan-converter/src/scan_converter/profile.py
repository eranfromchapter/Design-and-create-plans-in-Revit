"""DXF input profile v1 (see PROFILE.md): layer vocabulary and opening defaults.

The profile is a DOCUMENTED ASSUMPTION about Polycam floor-plan exports — Polycam
publishes layer names but not entity-level encoding. Everything here is a named
constant so the first real export can be diffed against it (gate calibration item
in docs/MANUAL_REVIT_TEST.md)."""

from __future__ import annotations

import re

# Case-insensitive layer synonym tables. A layer matches if its upper-cased name
# is in the set. AutoCAD AIA-style names included alongside Polycam's plain ones.
WALL_LAYERS = {"WALLS", "WALL", "A-WALL"}
DOOR_LAYERS = {"DOORS", "DOOR", "A-DOOR"}
WINDOW_LAYERS = {"WINDOWS", "WINDOW", "A-GLAZ"}
ROOM_LAYERS = {"ROOMS", "ROOM", "A-AREA"}

# Layer names that signal a multi-storey export (a 2D floor-plan bundle must be
# exactly one level; PLAN.md D1 forbids silent flattening).
MULTILEVEL_LAYER_RE = re.compile(r"(?i)(LEVEL|FLOOR|STOREY|STORY)[ _-]?([2-9]|1[0-9])\b")

# Opening defaults: a 2D DXF carries widths (segment length) but no heights, sills
# or swings. These are assumptions surfaced verbatim in the review payload.
DOOR_HEIGHT_MM = 2040.0
DOOR_SWING = "L"
WINDOW_SILL_MM = 900.0
WINDOW_HEIGHT_MM = 1400.0

# Geometry tolerances (mm / degrees).
MAX_SAGITTA_MM = 10.0  # arc tessellation bound (PLAN.md Phase 2)
HEADING_SNAP_DEG = 1.5  # snap-to-dominant-axis tolerance
ENDPOINT_MERGE_MIN_MM = 25.0  # corner-closure tolerance floor (else thickness/2)
OPENING_HOST_SLACK_MM = 50.0  # opening endpoint must lie within t/2 + slack of host
ELEVATION_CLUSTER_MM = 100.0  # >1 elevation cluster farther apart than this = multi-level
