"""Byte pins for the six Phase 6 goldens (written by scripts/gen_golden_mep.py, the
sole source of truth) plus the real-sim commit of the merged Commit #2 and the
recovery replay — the drift tests for every constant the e2e suite copies."""

from __future__ import annotations

import json

from mep_helpers import golden_chain, golden_plan
from revit_sim.model import Catalogs

from layout_compiler.golden_mep import (
    EXPECTED_SHIFTS,
    FILES,
    INJECTED_PAIR,
    compact_plan,
    dumps,
    gate_note,
    merge_golden,
    recovery_golden,
    rejected_sequence,
)
from layout_compiler.replay import sim_model_from_layout


def test_mep_plan_and_merged_card_are_byte_golden():
    chain, plan = golden_chain(), golden_plan()
    assert dumps(compact_plan(plan)) == FILES["mep_json"].read_text()
    merged = merge_golden(chain, plan)
    assert merged["status"] == "clean"
    assert merged["svgs"]["merged"] == FILES["mep_svg"].read_text()
    assert merged["svgs"]["merged"].count('class="device') == plan["counts"]["devices"]
    assert 'class="stack sanitary"' in merged["svgs"]["merged"]
    report = FILES["clash_report"].read_text()
    assert dumps({"clash_report": merged["clash_report"], "counts": merged["counts"]}) == report
    assert json.loads(report)["clash_report"]["open_clashes"] == []


def test_merged_commit2_commits_in_the_real_sim():
    chain, plan = golden_chain(), golden_plan()
    merged = merge_golden(chain, plan)
    catalogs = Catalogs.load()
    model = sim_model_from_layout(chain["commit0"])
    for op in [*chain["commit1_ops"], *merged["ops"]]:
        model.apply(op["op"], op["args"], catalogs)  # incl. run_interference_check
    assert len(model.pipes) == plan["counts"]["pipes"]
    assert len(model.devices) == plan["counts"]["devices"]
    assert len(model.conduits) == plan["counts"]["conduits"]


def test_recovery_and_exhaustion_are_byte_golden():
    chain, plan = golden_chain(), golden_plan()
    recovery = recovery_golden(chain, plan)
    assert dumps(recovery) == FILES["recovery_json"].read_text()
    plans = recovery["recovery"]["plans"]
    assert [p["status"] for p in plans] == ["clean", "clean"]
    assert [p["iterations_used"] for p in plans] == [1, 2]
    shifts = [
        next(d["after"]["offset"] for d in p["ops_diff"] if d["id"] == "E-001") for p in plans
    ]
    assert shifts == EXPECTED_SHIFTS
    statuses = [s["status"] for s in recovery["exhaustion"]["sequence"]]
    assert statuses == ["clean", "clean", "clean", "clean", "budget_exhausted"]
    final = rejected_sequence(chain, plan, 2)[-1]
    assert final["svgs"]["merged"] == FILES["recovery_svg"].read_text()
    assert final["svgs"]["merged"] != FILES["mep_svg"].read_text()  # E-001 moved
    assert recovery["injected_pair"] == INJECTED_PAIR


def test_gate_note_is_byte_golden_and_shows_both_sides_of_the_pins():
    chain, plan = golden_chain(), golden_plan()
    note = gate_note(chain, plan, merge_golden(chain, plan))
    assert dumps(note) == FILES["gate_note"].read_text()
    assert len(note["pin_08_p4_length"]["default"]["stacks"]) == 2
    assert len(note["pin_08_p4_length"]["alternative"]["stacks"]) == 3  # L = leg + along
    assert note["pin_13_stack_zones"]["default"]["devices"] == plan["counts"]["devices"]
    assert note["right_face_devices"]
