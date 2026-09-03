"""plan_mep end to end on the golden chain and its failure paths: MepPlan shape and
counts, the furnished pane byte-identical to the Phase 5 golden card, registry-valid
ops, blocking plans without confirmations, contract refusals, hard timeout."""

from __future__ import annotations

import pytest
from mep_helpers import GOLDEN_CONFIRMATIONS, golden_chain

from layout_compiler.golden_4br import REPO_ROOT
from layout_compiler.mep import plan as plan_mod
from layout_compiler.mep.inputs import MepError
from layout_compiler.mep.ops import validate_ops
from layout_compiler.mep.plan import MepOptions, plan_mep

PHASE5_SVG = (REPO_ROOT / "fixtures" / "goldens" / "phase5_2br_furnished.svg").read_text()


def run(confirmations=GOLDEN_CONFIRMATIONS, **over):
    g = golden_chain()
    kwargs = dict(
        commit0_layout=g["commit0"],
        commit1_layout=g["commit1_layout"],
        commit1_ops=g["commit1_ops"],
        interior_ops=g["interior_ops"],
        furnished_layout=g["furnished"],
        placer_wall_ids=g["placer_wall_ids"],
        confirmations=confirmations,
        opts=MepOptions(project_id=g["brief"]["meta"]["project_id"]),
    )
    kwargs.update(over)
    return plan_mep(**kwargs)


def test_golden_plan_shape_and_counts():
    plan = run()
    assert plan["blocking"] == [] and plan["counts"]["blocking"] == 0
    assert plan["counts"]["stacks"] == 2 and plan["counts"]["pipes"] == 10
    assert plan["counts"]["devices"] == 45
    assert plan["counts"]["switch"] == 11 and plan["counts"]["receptacle_240"] == 1
    assert plan["counts"]["extensions"] == {"appliance": 3}
    assert plan["counts"]["conduits"] == len(plan["home_runs"]) + sum(
        1
        for op in plan["ops"]
        if op["op"] == "create_conduit"
        and op["args"]["id"] not in {h["conduit_id"] for h in plan["home_runs"]}
    )
    assert [op["op"] for op in plan["ops"]] == (
        ["create_pipe"] * 10
        + ["place_device"] * 45
        + ["create_conduit"] * plan["counts"]["conduits"]
    )
    validate_ops(plan["ops"])
    assert plan["layout"]["meta"]["levels"] == {
        "floor_z": 0.0,
        "ceiling_z": 2700.0,
        "slab_to_slab": 3000.0,
    }
    assert plan["layout"]["meta"]["electrical"] == {"panel": [8050.0, 5200.0]}
    assert plan["inputs"]["panel_wall_id"] == "W-019"
    assert {s["wall_id"] for s in plan["stacks"]} == {"W-004", "W-026"}
    assert plan["diagnostics"]["counters"]["graph_nodes"] == 81
    assert plan["diagnostics"]["elapsed_ms"] >= 0


def test_golden_furnished_pane_is_the_phase5_card_and_mep_pane_has_symbols():
    plan = run()
    assert plan["svgs"]["furnished"] == PHASE5_SVG
    mep = plan["svgs"]["mep"]
    assert mep != PHASE5_SVG
    assert mep.count('class="device ') == 45
    assert mep.count('class="stack sanitary"') == 2
    assert mep.count('class="pipe sanitary"') == 8
    assert mep.count('class="conduit"') == plan["counts"]["conduits"]


def test_plan_is_deterministic():
    a, b = run(), run()
    a["diagnostics"].pop("elapsed_ms")
    b["diagnostics"].pop("elapsed_ms")
    assert a == b


def test_without_confirmations_the_plan_is_blocking_but_still_a_card():
    plan = run(confirmations={})
    assert plan["blocking"] == ["levels_missing", "panel_missing"]
    assert plan["counts"]["blocking"] == 2
    assert plan["stacks"] == [] and plan["home_runs"] == []  # no plumbing, no routing
    assert plan["counts"]["devices"] == 45  # E-1..E-3 still run
    assert all(op["op"] == "place_device" for op in plan["ops"])
    assert "levels" not in plan["layout"]["meta"] and "electrical" not in plan["layout"]["meta"]


def test_panel_off_every_wall_is_a_422_code():
    with pytest.raises(MepError) as err:
        run(confirmations={"panel": [5000.0, 3700.0], "slab_to_slab_mm": 3000.0})
    assert err.value.code == "panel_not_on_wall"


def test_invalid_layouts_are_refused_by_code():
    with pytest.raises(MepError) as err:
        run(commit1_layout={"meta": {}})
    assert err.value.code == "commit1_layout_invalid"
    with pytest.raises(MepError) as err:
        run(furnished_layout={"meta": {}})
    assert err.value.code == "furnished_layout_invalid"


def test_timeout_is_a_hard_error(monkeypatch):
    monkeypatch.setattr(plan_mod, "MEP_TIME_LIMIT_S", 0.0)
    with pytest.raises(MepError) as err:
        run()
    assert err.value.code == "mep_timeout"
