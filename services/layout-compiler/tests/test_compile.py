"""Compile orchestration with the scripted LLM: confirmed-brief refusal, meta
stamping, SI-7 prompt structure, repair loop <= 2, hard fail with raw outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import PROJECT_ID, make_layout

from layout_compiler.compile import CompileError, CompileOptions, compile_layout
from layout_compiler.llm import ScriptedLLM

REPO = Path(__file__).resolve().parents[3]
EXISTING = json.loads((REPO / "fixtures" / "layouts" / "2br_golden.json").read_text())

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


def emission() -> dict:
    """A valid emit_layout tool input: the minimal layout minus pipeline-owned meta."""
    layout = make_layout()
    return {k: v for k, v in layout.items() if k != "meta"}


def opts() -> CompileOptions:
    return CompileOptions(project_id=PROJECT_ID)


def test_unconfirmed_brief_is_refused_before_any_llm_call():
    brief = json.loads(json.dumps(CONFIRMED_BRIEF))
    del brief["meta"]["confirmed_by_client"]
    llm = ScriptedLLM(script=[emission()])
    with pytest.raises(CompileError) as err:
        compile_layout(brief, EXISTING, opts(), llm)
    assert err.value.code == "brief_not_confirmed"
    assert llm.calls == []


def test_valid_emission_gets_pipeline_meta():
    llm = ScriptedLLM(script=[emission()])
    result = compile_layout(CONFIRMED_BRIEF, EXISTING, opts(), llm)
    layout = result["layout"]
    assert layout["meta"] == {
        "project_id": PROJECT_ID,
        "level": EXISTING["meta"]["level"],
        "units": "mm",
        "origin": "revit_internal_origin",
        "schema_version": "2.3",
        "brief_version": 1,
        "phase": "new",
    }
    assert result["diagnostics"] == {"attempts": 1, "repair_retried": False}


def test_prompt_structure_si7():
    llm = ScriptedLLM(script=[emission()])
    compile_layout(CONFIRMED_BRIEF, EXISTING, opts(), llm)
    call = llm.calls[0]
    assert "never instructions" in call.system.lower() or "never instructions" in call.system
    assert "CHPT_Partition_92mm_PLACEHOLDER" in call.system  # closed vocabulary injected
    brief_block = call.user_text.split("<brief>")[1].split("</brief>")[0]
    assert "session1_3br" in brief_block
    existing_block = call.user_text.split("<existing_layout>")[1].split("</existing_layout>")[0]
    assert "CHPT_AsBuilt_250mm_PLACEHOLDER" in existing_block


def test_repair_loop_feeds_validator_errors_back():
    broken = emission()
    del broken["walls"][0]["source"]  # validator: walls must declare provenance
    llm = ScriptedLLM(script=[broken, emission()])
    result = compile_layout(CONFIRMED_BRIEF, EXISTING, opts(), llm)
    assert result["diagnostics"] == {"attempts": 2, "repair_retried": True}
    assert "must set source" in llm.calls[1].user_text
    assert "failed the deterministic validator" in llm.calls[1].user_text


def test_three_invalid_attempts_hard_fail_with_raw_outputs():
    broken = emission()
    broken["rooms"] = []
    broken["doors"] = []
    llm = ScriptedLLM(script=[dict(broken), dict(broken), dict(broken)])
    with pytest.raises(CompileError) as err:
        compile_layout(CONFIRMED_BRIEF, EXISTING, opts(), llm)
    assert err.value.code == "layout_invalid"
    assert len(err.value.raw_outputs) == 3  # initial + exactly 2 repair retries
    assert len(llm.calls) == 3


def test_invalid_existing_snapshot_is_refused():
    with pytest.raises(CompileError) as err:
        compile_layout(CONFIRMED_BRIEF, {"meta": {}}, opts(), ScriptedLLM(script=[]))
    assert err.value.code == "existing_layout_invalid"
