"""make demo-phase4 helper: runs the recorded 4BR compile against the frozen
2BR fixture and writes the side-by-side review-card artifacts to out/phase4/."""

from __future__ import annotations

import json

from layout_compiler.compile import CompileOptions, compile_layout
from layout_compiler.fixtures import FixtureLLM
from layout_compiler.golden_4br import REPO_ROOT, frozen_layout


def main() -> None:
    brief = json.loads((REPO_ROOT / "fixtures" / "briefs" / "2br_golden_brief.json").read_text())
    brief["meta"]["confirmed_by_client"] = True  # the gateway stamps this on approval
    result = compile_layout(
        brief,
        frozen_layout(),
        CompileOptions(project_id=brief["meta"]["project_id"]),
        FixtureLLM(),
    )
    out = REPO_ROOT / "out" / "phase4"
    out.mkdir(parents=True, exist_ok=True)
    (out / "existing_plan.svg").write_text(result["svgs"]["existing"])
    (out / "new_plan.svg").write_text(result["svgs"]["new"])
    (out / "ops.json").write_text(json.dumps(result["ops"], indent=2) + "\n")
    demolition = [d["id"] for d in result["demolition"]]
    print(f"demo-phase4: side-by-side card SVGs at {out}/existing_plan.svg + new_plan.svg")
    print(f"demo-phase4: {len(result['ops'])} ops, demolition {demolition}")


if __name__ == "__main__":
    main()
