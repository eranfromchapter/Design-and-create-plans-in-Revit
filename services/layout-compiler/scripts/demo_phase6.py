"""make demo-phase6 helper: recorded compile + furnish, deterministic MEP plan,
merge gate plan 1, the two-reject recovery replay and the gate note — written to
out/phase6/ as the review-card artifacts a human eyeballs at the Phase 6 gate."""

from __future__ import annotations

import json

from layout_compiler.golden_4br import REPO_ROOT
from layout_compiler.golden_mep import (
    gate_note,
    golden_chain,
    merge_golden,
    plan_golden,
    recovery_golden,
)


def main() -> None:
    chain = golden_chain()
    plan = plan_golden(chain)
    merged = merge_golden(chain, plan)
    recovery = recovery_golden(chain, plan)
    note = gate_note(chain, plan, merged)
    out = REPO_ROOT / "out" / "phase6"
    out.mkdir(parents=True, exist_ok=True)
    (out / "mep_plan.svg").write_text(plan["svgs"]["mep"])
    (out / "merged_plan.svg").write_text(merged["svgs"]["merged"])
    (out / "ops.json").write_text(json.dumps(merged["ops"], indent=2) + "\n")
    (out / "clash_report.json").write_text(json.dumps(merged["clash_report"], indent=2) + "\n")
    (out / "review_items.json").write_text(json.dumps(plan["review_items"], indent=2) + "\n")
    (out / "recovery.json").write_text(json.dumps(recovery, indent=2) + "\n")
    (out / "gate_note.json").write_text(json.dumps(note, indent=2) + "\n")
    c = plan["counts"]
    print(f"demo-phase6: MEP + merged Commit #2 card SVGs at {out}/mep_plan.svg + merged_plan.svg")
    print(
        f"demo-phase6: {c['stacks']} stacks / {c['pipes']} pipes, {c['devices']} devices "
        f"({c['switch']} switches, {c['gfci']} gfci, {c['receptacle_240']} 240V), "
        f"{c['conduits']} conduits; merge {merged['status']} → {merged['counts']['ops']} ops, "
        f"Phase A clashes {len(merged['clash_report']['open_clashes'])}"
    )
    plans = recovery["recovery"]["plans"]
    shifts = [
        next(d["after"]["offset"] for d in p["ops_diff"] if d["id"] == "E-001") for p in plans
    ]
    print(
        f"demo-phase6: recovery — {len(plans)} injected rejects of "
        f"{recovery['injected_pair']['a_id']}~{recovery['injected_pair']['b_id']}, "
        f"E-001 → {shifts}, "
        f"commits at plan {recovery['recovery']['commits_at_plan']} with "
        f"iterations_used={recovery['recovery']['final_iterations_used']}; "
        f"exhaustion: {[s['status'] for s in recovery['exhaustion']['sequence']]}"
    )
    blocking = [i for i in plan["review_items"] if i["severity"] == "blocking"]
    print(
        f"demo-phase6: {len(plan['review_items'])} review items ({len(blocking)} blocking); "
        f"gate note at {out}/gate_note.json"
    )


if __name__ == "__main__":
    main()
