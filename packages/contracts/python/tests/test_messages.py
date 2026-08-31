import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from chapter_contracts.generated.brief import ClientBrief

CONTRACTS = Path(__file__).resolve().parents[2]
WSS = Draft202012Validator(
    json.loads((CONTRACTS / "schemas" / "wss-messages.v1.json").read_text()),
    format_checker=FormatChecker(),
)
BRIEF_SCHEMA = Draft202012Validator(
    json.loads((CONTRACTS / "schemas" / "brief.v1.json").read_text()),
    format_checker=FormatChecker(),
)

HELLO = {
    "type": "hello",
    "workstation_id": "ws-design-01",
    "plugin_version": "0.1.0",
    "last_committed_seq": 0,
    "id_map_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}

COMMIT_RESULT = {
    "type": "commit_result",
    "envelope_id": "0b5e7a1c-2d3f-4a5b-8c9d-0e1f2a3b4c5d",
    "status": "rolled_back",
    "id_map_delta": [],
    "errors": [{"op_index": 3, "code": "interference", "message": "hard clash"}],
}

BRIEF = {
    "meta": {
        "project_id": "6f1c2a3e-9b4d-4c5e-8f70-123456789abc",
        "brief_version": 1,
        "source_sessions": ["session_01"],
        "confirmed_by_client": True,
    },
    "rooms_required": [{"program": "bedroom", "count": 2}],
    "adjacency_rules": [{"a": "kitchen", "b": "dining", "relation": "open_to"}],
    "style_tags": ["prewar", "warm minimal"],
}


def test_wss_messages_validate():
    assert WSS.is_valid(HELLO)
    assert WSS.is_valid(COMMIT_RESULT)


def test_wss_rejects_unknown_type_and_bad_status():
    assert not WSS.is_valid({"type": "exec_shell", "cmd": "rm -rf /"})
    bad = dict(COMMIT_RESULT, status="maybe")
    assert not WSS.is_valid(bad)


def test_brief_validates_both_ways():
    assert BRIEF_SCHEMA.is_valid(BRIEF)
    brief = ClientBrief.model_validate(BRIEF)
    assert brief.meta.brief_version == 1
