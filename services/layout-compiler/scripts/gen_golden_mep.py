"""Writes the six Phase 6 goldens AND proves them against the real pipeline: compile
(recorded) → furnish (recorded emission, real placer) → plan_mep → merge plan 1
clean → real SimModel replay incl. run_interference_check → recovery replay
reproduces the pinned shifts → two-run byte determinism → write. The OUTPUT of
this script is the sole source of golden truth — tests/e2e constants are copied
from it, never the other way round.

  uv run python scripts/gen_golden_mep.py
"""

from __future__ import annotations

import json

from revit_sim.model import Catalogs

from layout_compiler.golden_4br import REPO_ROOT
from layout_compiler.golden_mep import (
    EXHAUSTION_REJECTS,
    EXPECTED_SHIFTS,
    FILES,
    compact_plan,
    dumps,
    gate_note,
    golden_chain,
    merge_golden,
    plan_golden,
    recovery_golden,
)
from layout_compiler.mep.ops import validate_ops
from layout_compiler.merge.clash import phase_a
from layout_compiler.merge.prisms import build_prisms
from layout_compiler.replay import sim_model_from_layout
from layout_compiler.validator import validate_layout

PHASE5_SVG = REPO_ROOT / "fixtures" / "goldens" / "phase5_2br_furnished.svg"


def build() -> dict[str, str]:
    chain = golden_chain()
    plan = plan_golden(chain)
    assert plan["blocking"] == [], plan["blocking"]
    validate_ops(plan["ops"])
    assert plan["svgs"]["furnished"] == PHASE5_SVG.read_text(), "furnished pane drifted"
    print(
        f"plan: {plan['counts']['stacks']} stacks, {plan['counts']['pipes']} pipes, "
        f"{plan['counts']['devices']} devices, {plan['counts']['conduits']} conduits, "
        f"{plan['counts']['review_items']} review items"
    )
    for stack in plan["stacks"]:
        print(
            f"  {stack['id']} on {stack['wall_id']} at {stack['xy']} "
            f"Ø{stack['diameter']} {stack['fixtures']}"
        )

    merged = merge_golden(chain, plan)
    assert merged["status"] == "clean", merged["status"]
    assert merged["iterations_used"] == 0 and merged["actions"] == []
    assert validate_layout(merged["layout"]) == []
    assert merged["interior"]["ops_verbatim"] is True
    validate_ops(merged["ops"][:-1])
    branch_fixtures = {b["id"]: b["fixture_ids"] for b in plan["branches"]}
    assert phase_a(build_prisms(merged["layout"], plan["ops"], branch_fixtures)) == []
    print(f"merge plan 1: {merged['status']}, {merged['counts']}")

    # the executor's own law: replay Commit #0 + #1 + the merged Commit #2 ops INCLUDING
    # the trailing run_interference_check into the real sim — it must commit
    catalogs = Catalogs.load()
    model = sim_model_from_layout(chain["commit0"])
    for op in [*chain["commit1_ops"], *merged["ops"]]:
        model.apply(op["op"], op["args"], catalogs)
    print(f"real sim replay: {len(merged['ops'])} ops applied, interference check passed")

    recovery = recovery_golden(chain, plan)
    shifts = [
        next(d["after"]["offset"] for d in p["ops_diff"] if d["id"] == "E-001")
        for p in recovery["recovery"]["plans"]
    ]
    assert shifts == EXPECTED_SHIFTS, shifts
    assert recovery["recovery"]["commits_at_plan"] == 3
    assert recovery["recovery"]["final_iterations_used"] == 2
    statuses = [s["status"] for s in recovery["exhaustion"]["sequence"]]
    assert statuses == ["clean"] * EXHAUSTION_REJECTS + ["budget_exhausted"], statuses
    print(f"recovery: E-001 {shifts}; exhaustion: {statuses}")
    plan3 = recovery["recovery"]["plans"][-1]
    final = merge_golden(
        chain, plan, 1, 3, recovery["recovery"]["plans"][0]["actions"], [recovery["injected_pair"]]
    )
    assert final["actions"] == plan3["actions"]

    note = gate_note(chain, plan, merged)
    print(
        "gate note: PIN-08 alternative → "
        f"{len(note['pin_08_p4_length']['alternative']['stacks'])} stacks; "
        f"PIN-13 alternative → {note['pin_13_stack_zones']['alternative']['devices']} devices; "
        f"right-face devices {len(note['right_face_devices'])}"
    )
    return {
        "mep_svg": merged["svgs"]["merged"],
        "mep_json": dumps(compact_plan(plan)),
        "clash_report": dumps({"clash_report": merged["clash_report"], "counts": merged["counts"]}),
        "recovery_json": dumps(recovery),
        "recovery_svg": final["svgs"]["merged"],
        "gate_note": dumps(note),
    }


def main() -> None:
    first = build()
    second = build()
    assert first == second, "two runs differ — the generator is not deterministic"
    for key, text in first.items():
        FILES[key].write_text(text)
        print(f"wrote {FILES[key].relative_to(REPO_ROOT)} ({len(text)} bytes)")
    counts = json.loads(first["clash_report"])["counts"]
    print(f"phase6 goldens written; merged Commit #2 = {counts['ops']} ops")


if __name__ == "__main__":
    main()
