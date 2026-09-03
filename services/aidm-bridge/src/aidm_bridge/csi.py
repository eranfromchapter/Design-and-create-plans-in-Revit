"""CSI MasterFormat section -> the Phase 7 surface class a SKU can be selected for
(docs/PHASE7_DESIGN.md P7-08). The mapping is an engineering table, not catalog
vocabulary: nothing is invented per SKU, and an unmapped section is simply not
selectable (info `unmapped_csi`)."""

from __future__ import annotations

SURFACES = ("wall", "casework", "door", "plumbing_fixture")

# first two MasterFormat levels -> surface
_SURFACE_BY_PREFIX: dict[tuple[str, str], str] = {
    ("09", "91"): "wall",  # painting
    ("09", "93"): "wall",  # staining and transparent finishing
    ("09", "30"): "wall",  # tiling
    ("09", "72"): "wall",  # wall coverings
    ("09", "29"): "wall",  # gypsum board (finish)
    ("06", "41"): "casework",  # architectural wood casework
    ("12", "35"): "casework",  # specialty / residential casework
    ("08", "14"): "door",  # wood doors
    ("08", "11"): "door",  # metal doors and frames
    ("08", "16"): "door",  # composite doors
    ("22", "41"): "plumbing_fixture",  # residential plumbing fixtures
    ("22", "42"): "plumbing_fixture",  # commercial plumbing fixtures
}

# the allowlist category vocabulary a surface's targets belong to
CATEGORY_BY_SURFACE = {
    "wall": "walls",
    "casework": "casework",
    "door": "doors",
    "plumbing_fixture": "plumbing",
}


def surface_of(csi_section: str) -> str | None:
    parts = csi_section.split()
    if len(parts) < 2:
        return None
    return _SURFACE_BY_PREFIX.get((parts[0], parts[1]))
