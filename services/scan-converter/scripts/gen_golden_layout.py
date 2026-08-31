"""Provenance script for fixtures/layouts/2br_golden.json — the converter's
layout for the canonical fixture DXF (run after deliberate geometry changes):

    cd services/scan-converter && uv run scripts/gen_golden_layout.py
"""

from __future__ import annotations

import json
from pathlib import Path

from scan_converter.lane_a import ConvertOptions, convert

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / ".." / "fixtures" / "scans" / "2br_uws.dxf"
OUT = REPO / ".." / "fixtures" / "layouts" / "2br_golden.json"

# The golden uses a fixed synthetic project id; the gateway rewrites meta.project_id
# to the real project when it converts a bundle (test helper id, matches conftest).
PROJECT_ID = "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01"


def main() -> None:
    result = convert(FIXTURE.read_bytes(), ConvertOptions(project_id=PROJECT_ID))
    OUT.resolve().write_text(json.dumps(result["layout"], indent=2) + "\n")
    print(f"wrote {OUT.resolve()}")


if __name__ == "__main__":
    main()
