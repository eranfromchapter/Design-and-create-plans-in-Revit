"""Every Phase 6 constant, in mm (PLAN.md Part G; CLAUDE.md: every scoring constant
stated in mm). Interpretation switches are pinned decisions (docs/PHASE6_DESIGN.md
"Pinned decisions"); flipping one regenerates the Phase 6 goldens."""

from __future__ import annotations

# P-1 riser bias: 0.0005 FU/mm == 0.5 FU/m (Part G, unit-sanity property test)
LAMBDA_FU_PER_MM = 0.0005

# E-1 receptacles
E1_INSET_MM = 1830.0
E1_DEFAULT_SPACING_MM = 3660.0
E1_MIN_RUN_MM = 610.0
E1_DEDUPE_MM = 300.0
E1_HEIGHT_AFL_MM = 380.0
E1_MIN_OUTLET_SPACING_MM = 610.0  # constraints.outlet_spacing below this is a blocking item

# E-2 counters / bathroom GFCI
E2_INSET_MM = 610.0
E2_SPACING_MM = 1220.0
E2_HEIGHT_AFL_MM = 1150.0
E2_BASIN_MAX_MM = 914.0
E2_COUNTER_FALLBACK_EXTEND_MM = 600.0

# E-3 switches
E3_JAMB_OFFSET_MM = 150.0
E3_HEIGHT_AFL_MM = 1220.0
E3_CORNER_FALLBACK_MM = 300.0

# E-4 home runs
E4_PENETRATION_PENALTY_MM = 4000.0  # 4 m equivalent per fire-rated penetration (v1.1)
E4_STACK_EXCLUSION_MM = 300.0  # wet-stack exclusion prism: stack +/- 300
E4_CONDUIT_Z_MM = 2600.0
E4_CONDUIT_DIAMETER_MM = 21.0
E4_MAX_PATH_POINTS = 100

# devices
DEVICE_EDGE_MM = 50.0  # a device needs 50 mm of run on each side of its centre
DEVICE_B2B_MM = 100.0  # back-to-back: same wall, |d offset| < 100, |d height| < 100
DEVICE_SHIFT_MM = 150.0
DEVICE_SHIFT_TRIES = 8
APPLIANCE_SHIFT_MAX_MM = 600.0

# plumbing
STACK_MIN_DIAMETER_MM = 51.0
STACK_WC_DIAMETER_MM = 76.0
STACK_SNAP_MARGIN_MM = 50.0
RISER_ADJACENT_MM = 300.0
HALLWAY_RECEPTACLE_MIN_EDGE_MM = 3000.0
PANEL_MAX_WALL_DIST_MM = 600.0
SLAB_TO_SLAB_MIN_MM = 2100.0
SLAB_TO_SLAB_MAX_MM = 6000.0

# bounds (SI-6)
MAX_STACKS = 4
MAX_P1_ITERATIONS = 16
MERGE_BUDGET = 3

# request-boundary time limits (wall clock lives ONLY in plan.py / gate.py)
MEP_TIME_LIMIT_S = 60.0
MERGE_TIME_LIMIT_S = 60.0

GRAPH_NODE_TOL_MM = 1.0
COORD_ROUND = 1  # decimals: every emitted coordinate is rounded to 0.1 mm

# interpretation switches (defaults = the Part G letter; see Pinned decisions)
P4_L_INCLUDES_DRAIN_LEG = False  # PIN-08 (Eran 2026-09-02: spec-literal L = along)
ZONES_BREAK_DEVICE_RUNS = False  # PIN-13
WINDOWS_BREAK_RUNS_ALWAYS = False  # PIN-12
P1_EXCLUDE_SI8_WALLS = True  # PIN-05
EXTENSION_APPLIANCE_RECEPTACLES = True  # PIN-20
