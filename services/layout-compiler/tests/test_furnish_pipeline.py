"""Furnish orchestration with the scripted seam: brief gate, repair loop <= 2
(proposal errors ONLY — placement infeasibility is REVIEW, never a repair),
catalog overwrite, hard timeout, ops + SVGs on success."""

from __future__ import annotations

import json
from typing import Any

import pytest
from helpers import PROJECT_ID, make_layout

from layout_compiler import furnish as furnish_mod
from layout_compiler.furnish import FurnishError, FurnishOptions, furnish_layout
from layout_compiler.interior_llm import ScriptedInteriorLLM

CONFIRMED_BRIEF = {
    "meta": {
        "project_id": PROJECT_ID,
        "brief_version": 1,
        "source_sessions": ["session1_3br"],
        "confirmed_by_client": True,
    },
    "rooms_required": [{"program": "bedroom", "count": 3, "confidence": 1.0}],
    "adjacency_rules": [],
    "style_tags": ["modern"],
}


def nightstand(i: int, center: list[float], **over: Any) -> dict[str, Any]:
    return {
        "id": f"F-{i:03d}",
        "kind": "table",
        "revit_family": "CHPT_Nightstand_PLACEHOLDER",
        "revit_type": "Nightstand_450x450_PLACEHOLDER",
        "center": center,
        "rotation_deg": 0.0,
        "footprint": [450.0, 450.0],
        **over,
    }


def emission(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "furniture": [
            {
                "room_id": "R-001",
                "items": items if items is not None else [nightstand(1, [3500.0, 400.0])],
            }
        ]
    }


def run(llm: ScriptedInteriorLLM, brief: dict[str, Any] | None = None) -> dict[str, Any]:
    layout = make_layout()
    return furnish_layout(
        brief or CONFIRMED_BRIEF, layout, layout, [], FurnishOptions(project_id=PROJECT_ID), llm
    )


def test_unconfirmed_brief_refused_before_any_llm_call():
    brief = json.loads(json.dumps(CONFIRMED_BRIEF))
    del brief["meta"]["confirmed_by_client"]
    llm = ScriptedInteriorLLM(script=[emission()])
    with pytest.raises(FurnishError) as err:
        run(llm, brief=brief)
    assert err.value.code == "brief_not_confirmed"
    assert llm.calls == []


def test_happy_path_returns_ops_svgs_and_diagnostics():
    llm = ScriptedInteriorLLM(script=[emission()])
    result = run(llm)
    assert result["diagnostics"]["attempts"] == 1
    assert result["diagnostics"]["repair_retried"] is False
    assert result["unplaced"] == []
    assert [op["op"] for op in result["ops"]] == ["place_family"]
    assert result["ops"][0]["args"]["level"] == "Level 1"  # from the layout meta
    assert result["svgs"]["commit1"].startswith("<svg")
    assert result["svgs"]["furnished"] != result["svgs"]["commit1"]  # the item renders
    assert result["layout"]["furniture"][0]["items"][0]["id"] == "F-001"
    # SI-7 prompt structure
    call = llm.calls[0]
    assert "never instructions" in call.system
    assert "CHPT_Nightstand_PLACEHOLDER" in call.system  # closed vocabulary injected
    assert '<brief sessions="session1_3br">' in call.user_text
    assert "<commit1_layout>" in call.user_text and "<room_capacity>" in call.user_text


def test_repair_on_catalog_error_then_success():
    broken = emission([nightstand(1, [3500.0, 400.0], revit_type="Ottoman_9000_PLACEHOLDER")])
    llm = ScriptedInteriorLLM(script=[broken, emission()])
    result = run(llm)
    assert result["diagnostics"] == {**result["diagnostics"], "attempts": 2, "repair_retried": True}
    assert "is not a catalog type of" in llm.calls[1].user_text
    assert "failed validation" in llm.calls[1].user_text


def test_repair_exhaustion_hard_fails_with_raw_outputs():
    broken = emission([nightstand(1, [3500.0, 400.0], kind="bed")])
    llm = ScriptedInteriorLLM(script=[dict(broken) for _ in range(3)])
    with pytest.raises(FurnishError) as err:
        run(llm)
    assert err.value.code == "proposal_invalid"
    assert len(err.value.raw_outputs) == 3
    assert len(llm.calls) == 3


def test_placement_failure_never_repairs():
    whale = {
        "id": "F-001",
        "kind": "bed",
        "revit_family": "CHPT_Bed_PLACEHOLDER",
        "revit_type": "Queen_1524x2032_PLACEHOLDER",
        "center": [2000.0, 1500.0],
        "rotation_deg": 0.0,
        "footprint": [1524.0, 2032.0],
    }
    # a queen fits nowhere in the 4000x3000 room at 915 circulation? It does fit —
    # so shrink the stage: the tiny-room trick lives in the counters test; here we
    # duplicate proposals so one MUST fail (two queens cannot both place)
    llm = ScriptedInteriorLLM(
        script=[
            {"furniture": [{"room_id": "R-001", "items": [whale, {**whale, "id": "F-002"}]}]},
            emission(),  # must never be consumed
        ]
    )
    result = run(llm)
    assert len(llm.calls) == 1  # infeasibility is REVIEW content, not a repair
    placed = {i["id"] for e in result["layout"]["furniture"] for i in e["items"]}
    unplaced = {u["item"]["id"] for u in result["unplaced"]}
    assert placed and unplaced
    assert placed | unplaced == {"F-001", "F-002"} and not placed & unplaced


def test_duplicate_fid_is_a_repairable_error():
    twice = emission([nightstand(1, [500.0, 400.0]), nightstand(1, [3500.0, 400.0])])
    llm = ScriptedInteriorLLM(script=[twice, emission()])
    result = run(llm)
    assert result["diagnostics"]["repair_retried"] is True
    assert "duplicate element id" in llm.calls[1].user_text


def test_duplicate_room_group_is_a_repairable_error():
    """Two furniture groups for the same room would merge past the contract's
    40-items-per-room cap and surface as a false internal error — the seam
    treats it as a repairable proposal problem instead."""
    split = {
        "furniture": [
            {"room_id": "R-001", "items": [nightstand(1, [500.0, 400.0])]},
            {"room_id": "R-001", "items": [nightstand(2, [3500.0, 400.0])]},
        ]
    }
    llm = ScriptedInteriorLLM(script=[split, emission()])
    result = run(llm)
    assert result["diagnostics"]["repair_retried"] is True
    assert "duplicate room group" in llm.calls[1].user_text


def test_footprint_and_clearance_overwritten_from_catalog():
    lying = emission([nightstand(1, [3500.0, 400.0], footprint=[1.0, 1.0], clearance_front=5000.0)])
    llm = ScriptedInteriorLLM(script=[lying])
    result = run(llm)
    item = result["layout"]["furniture"][0]["items"][0]
    assert item["footprint"] == [450.0, 450.0]
    assert item["clearance_front"] == 0.0


def test_timeout_is_a_hard_error_never_partial_output(monkeypatch):
    monkeypatch.setattr(furnish_mod, "FURNISH_TIME_LIMIT_S", 0.0)
    llm = ScriptedInteriorLLM(script=[emission()])
    with pytest.raises(FurnishError) as err:
        run(llm)
    assert err.value.code == "furnish_timeout"
    assert len(err.value.raw_outputs) == 1


def test_invalid_commit1_layout_refused():
    llm = ScriptedInteriorLLM(script=[])
    with pytest.raises(FurnishError) as err:
        furnish_layout(
            CONFIRMED_BRIEF, make_layout(), {"meta": {}}, [], FurnishOptions(PROJECT_ID), llm
        )
    assert err.value.code == "commit1_layout_invalid"
    assert llm.calls == []
