"""make demo-phase5 helper: recorded compile + furnish against the frozen 2BR;
writes the interior review-card artifacts (Commit #1 vs furnished, side by
side) plus the ops and the REVIEW list to out/phase5/."""

from __future__ import annotations

import json

from layout_compiler.compile import CompileOptions, compile_layout
from layout_compiler.fixtures import FixtureLLM
from layout_compiler.furnish import FurnishOptions, furnish_layout
from layout_compiler.golden_4br import REPO_ROOT, frozen_layout
from layout_compiler.interior_fixtures import InteriorFixtureLLM


def main() -> None:
    brief = json.loads((REPO_ROOT / "fixtures" / "briefs" / "2br_golden_brief.json").read_text())
    brief["meta"]["confirmed_by_client"] = True  # the gateway stamps this on approval
    opts = CompileOptions(project_id=brief["meta"]["project_id"])
    compiled = compile_layout(brief, frozen_layout(), opts, FixtureLLM())
    result = furnish_layout(
        brief,
        frozen_layout(),
        compiled["layout"],
        compiled["ops"],
        FurnishOptions(project_id=brief["meta"]["project_id"]),
        InteriorFixtureLLM(),
    )
    out = REPO_ROOT / "out" / "phase5"
    out.mkdir(parents=True, exist_ok=True)
    (out / "commit1_plan.svg").write_text(result["svgs"]["commit1"])
    (out / "furnished_plan.svg").write_text(result["svgs"]["furnished"])
    (out / "ops.json").write_text(json.dumps(result["ops"], indent=2) + "\n")
    (out / "unplaced.json").write_text(json.dumps(result["unplaced"], indent=2) + "\n")
    placed = sum(len(e["items"]) for e in result["layout"]["furniture"])
    print(f"demo-phase5: side-by-side card SVGs at {out}/commit1_plan.svg + furnished_plan.svg")
    print(
        f"demo-phase5: {placed} items placed ({len(result['ops'])} place_family ops), "
        f"{len(result['unplaced'])} for REVIEW: "
        f"{[u['item']['id'] for u in result['unplaced']]}"
    )


if __name__ == "__main__":
    main()
