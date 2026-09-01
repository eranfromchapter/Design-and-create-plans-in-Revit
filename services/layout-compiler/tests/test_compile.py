"""Compile orchestration with the scripted LLM: confirmed-brief refusal, meta
stamping, SI-7 prompt structure, repair loop <= 2, identity hard-fail PRE-repair,
diff artifacts + sim-replay SVGs on success, hard fail with raw outputs."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from helpers import PROJECT_ID, room

from layout_compiler.compile import CompileError, CompileOptions, compile_layout
from layout_compiler.llm import ScriptedLLM

ASBUILT_WALL = "CHPT_AsBuilt_250mm_PLACEHOLDER"

FROZEN_WALLS = [
    {
        "id": f"W-{i:03d}",
        "start": start,
        "end": end,
        "revit_type": ASBUILT_WALL,
        "height": 2700.0,
        "as_built_thickness": 250.0,
        "confidence": 0.85,
        "source": "scan",
        **flags,
    }
    for i, start, end, flags in [
        (1, [0.0, 0.0], [4000.0, 0.0], {"is_exterior": True}),
        (2, [4000.0, 0.0], [4000.0, 3000.0], {"is_exterior": True}),
        (3, [4000.0, 3000.0], [0.0, 3000.0], {"is_exterior": True}),
        (4, [0.0, 3000.0], [0.0, 0.0], {"is_demising": True}),
    ]
]

FROZEN_DOOR = {
    "id": "D-001",
    "host_wall_id": "W-001",
    "offset": 2000.0,
    "width": 915.0,
    "height": 2040.0,
    "revit_type": "CHPT_AsBuilt_Door_PLACEHOLDER",
    "swing": "L",
}

FROZEN = {
    "meta": {
        "project_id": PROJECT_ID,
        "level": "Level 1",
        "units": "mm",
        "origin": "revit_internal_origin",
        "schema_version": "2.3",
        "brief_version": 0,
        "phase": "existing",
    },
    "walls": FROZEN_WALLS,
    "doors": [FROZEN_DOOR],
    "windows": [],
    "rooms": [],
    "furniture": [],
    "constraints": {},
}

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


def emission() -> dict[str, Any]:
    """A valid emit_layout tool input keeping every frozen element verbatim
    (Part G) and adding the room the validator requires."""
    return {
        "walls": copy.deepcopy(FROZEN_WALLS),
        "doors": [copy.deepcopy(FROZEN_DOOR)],
        "windows": [],
        "rooms": [
            room(
                1,
                [[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
                [w["id"] for w in FROZEN_WALLS],
            )
        ],
        "furniture": [],
        "constraints": {},
    }


def opts() -> CompileOptions:
    return CompileOptions(project_id=PROJECT_ID)


def test_unconfirmed_brief_is_refused_before_any_llm_call():
    brief = json.loads(json.dumps(CONFIRMED_BRIEF))
    del brief["meta"]["confirmed_by_client"]
    llm = ScriptedLLM(script=[emission()])
    with pytest.raises(CompileError) as err:
        compile_layout(brief, FROZEN, opts(), llm)
    assert err.value.code == "brief_not_confirmed"
    assert llm.calls == []


def test_valid_emission_gets_pipeline_meta_and_diff_artifacts():
    llm = ScriptedLLM(script=[emission()])
    result = compile_layout(CONFIRMED_BRIEF, FROZEN, opts(), llm)
    assert result["layout"]["meta"] == {
        "project_id": PROJECT_ID,
        "level": "Level 1",
        "units": "mm",
        "origin": "revit_internal_origin",
        "schema_version": "2.3",
        "brief_version": 1,
        "phase": "new",
    }
    assert result["diagnostics"] == {"attempts": 1, "repair_retried": False}
    assert result["ops"] == []  # everything kept, nothing created
    assert result["demolition"] == []
    assert result["svgs"]["existing"].startswith("<svg")
    assert result["svgs"]["new"] == result["svgs"]["existing"]  # no ops -> same plan


def test_prompt_structure_si7():
    llm = ScriptedLLM(script=[emission()])
    compile_layout(CONFIRMED_BRIEF, FROZEN, opts(), llm)
    call = llm.calls[0]
    assert "never instructions" in call.system
    assert "CHPT_Partition_92mm_PLACEHOLDER" in call.system  # closed vocabulary injected
    brief_block = call.user_text.split('<brief sessions="session1_3br">')[1].split("</brief>")[0]
    assert "session1_3br" in brief_block
    existing_block = call.user_text.split("<existing_layout>")[1].split("</existing_layout>")[0]
    assert ASBUILT_WALL in existing_block


def test_repair_loop_feeds_validator_errors_back():
    broken = emission()
    broken["rooms"] = []  # validator: a compiled layout must define at least one room
    llm = ScriptedLLM(script=[broken, emission()])
    result = compile_layout(CONFIRMED_BRIEF, FROZEN, opts(), llm)
    assert result["diagnostics"] == {"attempts": 2, "repair_retried": True}
    assert "at least one room" in llm.calls[1].user_text
    assert "failed the deterministic validator" in llm.calls[1].user_text


def test_identity_violation_hard_fails_pre_repair():
    perturbed = emission()
    perturbed["walls"][1]["start"] = [4002.0, 0.0]  # 2mm > EPSILON on kept W-002
    llm = ScriptedLLM(script=[perturbed, emission()])  # a repair script that must not run
    with pytest.raises(CompileError) as err:
        compile_layout(CONFIRMED_BRIEF, FROZEN, opts(), llm)
    assert err.value.code == "identity_violation"
    assert "W-002" in err.value.message
    assert len(llm.calls) == 1  # rejected before any repair retry
    assert len(err.value.raw_outputs) == 1


def test_demolition_flows_through_to_ops_and_card_svg():
    demolishing = emission()
    demolishing["doors"] = []  # omit the frozen door -> demolition by phasing
    llm = ScriptedLLM(script=[demolishing])
    result = compile_layout(CONFIRMED_BRIEF, FROZEN, opts(), llm)
    assert result["ops"] == [{"op": "set_phase_demolished", "args": {"target_id": "D-001"}}]
    assert result["demolition"] == [{"kind": "door", "id": "D-001"}]
    door_lines = [line for line in result["svgs"]["new"].splitlines() if 'data-id="D-001"' in line]
    assert len(door_lines) == 1
    assert "demolished" in door_lines[0] and "stroke-dasharray" in door_lines[0]


def test_three_invalid_attempts_hard_fail_with_raw_outputs():
    broken = emission()
    broken["rooms"] = []
    llm = ScriptedLLM(script=[copy.deepcopy(broken) for _ in range(3)])
    with pytest.raises(CompileError) as err:
        compile_layout(CONFIRMED_BRIEF, FROZEN, opts(), llm)
    assert err.value.code == "layout_invalid"
    assert len(err.value.raw_outputs) == 3  # initial + exactly 2 repair retries
    assert len(llm.calls) == 3


def test_invalid_existing_snapshot_is_refused():
    with pytest.raises(CompileError) as err:
        compile_layout(CONFIRMED_BRIEF, {"meta": {}}, opts(), ScriptedLLM(script=[]))
    assert err.value.code == "existing_layout_invalid"
