"""Writes the recorded furnish fixture from the golden_furniture table AND
proves it against the real pipeline: the fixture is regenerated, replayed
through furnish_layout (fixture mode), validated by the full validator, and
the furnished plan SVG golden is written. The OUTPUT of this script is the
sole source of golden truth — test/e2e constants are copied from it.

  uv run python scripts/gen_golden_furniture.py
"""

from __future__ import annotations

import json

from shapely.geometry import Polygon

from layout_compiler.compile import CompileOptions, compile_layout
from layout_compiler.fixtures import FixtureLLM
from layout_compiler.furnish import FurnishOptions, furnish_layout
from layout_compiler.geometry import room_free_space
from layout_compiler.golden_4br import REPO_ROOT, frozen_layout
from layout_compiler.golden_furniture import EXPECTED_UNPLACED, emission
from layout_compiler.interior_fixtures import InteriorFixtureLLM
from layout_compiler.validator import validate_layout

FIXTURE = REPO_ROOT / "fixtures" / "llm" / "furniture_golden_4br.json"
SVG_GOLDEN = REPO_ROOT / "fixtures" / "goldens" / "phase5_2br_furnished.svg"

# minimum post-furnish eroded free areas (m²) — regression floors, from this
# script's own verified output
MARGIN_FLOORS_M2 = {"R-002": 0.4, "R-003": 0.1, "R-007": 0.05, "R-008": 1.5, "R-009": 2.5}


def main() -> None:
    FIXTURE.write_text(json.dumps({"emission": emission()}, indent=2) + "\n")
    print(f"wrote {FIXTURE}")

    brief = json.loads((REPO_ROOT / "fixtures" / "briefs" / "2br_golden_brief.json").read_text())
    brief["meta"]["confirmed_by_client"] = True
    compiled = compile_layout(
        brief, frozen_layout(), CompileOptions(project_id=brief["meta"]["project_id"]), FixtureLLM()
    )
    result = furnish_layout(
        brief,
        frozen_layout(),
        compiled["layout"],
        compiled["ops"],
        FurnishOptions(project_id=brief["meta"]["project_id"]),
        InteriorFixtureLLM(),
    )

    furnished = result["layout"]
    oracle = validate_layout(furnished)
    assert oracle == [], oracle
    placed = [i["id"] for e in furnished["furniture"] for i in e["items"]]
    unplaced = [u["item"]["id"] for u in result["unplaced"]]
    print(f"placed {len(placed)}: {placed}")
    for entry in result["unplaced"]:
        print(f"UNPLACED {entry['item']['id']} ({entry['room_id']}): {entry['reason']}")
    assert unplaced == EXPECTED_UNPLACED, unplaced
    assert len(result["ops"]) == len(placed)

    circulation_min = float(furnished["constraints"]["circulation_min"])
    for room in furnished["rooms"]:
        polygon = Polygon(room["boundary"])
        items = [
            i for e in furnished["furniture"] if e["room_id"] == room["id"] for i in e["items"]
        ]
        eroded = room_free_space(polygon, items).buffer(-circulation_min / 2)
        area_m2 = eroded.area / 1e6
        floor = MARGIN_FLOORS_M2.get(room["id"])
        status = f" (floor {floor})" if floor else ""
        print(f"{room['id']} {room['program']:<10} eroded {area_m2:8.3f} m2{status}")
        if floor is not None:
            assert area_m2 >= floor, (room["id"], area_m2, floor)

    SVG_GOLDEN.write_text(result["svgs"]["furnished"])
    print(f"wrote {SVG_GOLDEN} ({len(result['svgs']['furnished'])} bytes)")
    print(
        f"diagnostics: attempts={result['diagnostics']['attempts']} "
        f"total_candidates={result['diagnostics']['total_candidates']} "
        f"spiral={result['diagnostics']['spiral_total']} "
        f"elapsed={result['diagnostics']['elapsed_ms']}ms"
    )


if __name__ == "__main__":
    main()
