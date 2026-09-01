"""Phase 3 acceptance (PLAN.md Part E): golden brief, injection with the zero-ops
assertion, contradiction recording, and the PII boundary test — all against the
committed fixture transcripts and the synthetic recorded extractions."""

from __future__ import annotations

import json
from pathlib import Path

from brief_extractor.extract import ExtractOptions, Session, extract_brief
from brief_extractor.fixtures import FixtureLLM
from brief_extractor.guard import assert_zero_ops
from brief_extractor.llm import ScriptedLLM

REPO = Path(__file__).resolve().parents[3]
TRANSCRIPTS = REPO / "fixtures" / "transcripts"
PROJECT_ID = "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01"


def _session(name: str) -> Session:
    return Session(name, (TRANSCRIPTS / f"{name}.txt").read_text())


def _opts(**kw) -> ExtractOptions:
    return ExtractOptions(project_id=PROJECT_ID, brief_version=1, **kw)


def test_golden_brief_from_two_fixture_sessions():
    """Fixture transcripts -> expected BriefSchema (semantic golden compare)."""
    result = extract_brief(
        [_session("session1_3br"), _session("session2_4br")], _opts(), FixtureLLM()
    )
    golden = json.loads((REPO / "fixtures" / "briefs" / "2br_golden_brief.json").read_text())
    assert result["brief"] == golden


def test_contradictions_recorded_latest_wins():
    """3BR in session 1, 4BR in session 2 -> latest wins + contradiction recorded;
    the deliberate finish-tier change is caught the same way."""
    result = extract_brief(
        [_session("session1_3br"), _session("session2_4br")], _opts(), FixtureLLM()
    )
    brief = result["brief"]
    bedroom = next(r for r in brief["rooms_required"] if r["program"] == "bedroom")
    assert bedroom["count"] == 4
    assert brief["finish_tier"] == "standard"
    fields = {c["field"] for c in brief["contradictions"]}
    assert fields == {"rooms_required.bedroom", "finish_tier"}
    assert all(c["resolution"] == "latest_wins" for c in brief["contradictions"])
    # non-conflicting session-1 facts survive reconciliation
    assert any(r["program"] == "bathroom" and r["count"] == 2 for r in brief["rooms_required"])
    assert "original cast-iron radiators" in brief["keep_items"]


def test_injection_fixture_zero_ops_anywhere():
    """Hostile transcript -> a normal brief or flags; ZERO op-registry strings in
    the output (assertion over the serialized brief)."""
    llm = FixtureLLM()
    result = extract_brief([_session("injection")], _opts(), llm)
    brief = result["brief"]
    assert_zero_ops(json.dumps(brief))
    # the useful requirements still came through
    assert any(r["program"] == "bedroom" and r["count"] == 2 for r in brief["rooms_required"])
    assert any("prompt injection" in q for q in brief["open_questions"])
    # and the hostile transcript reached the LLM only as delimited data (SI-7)
    system, user_text = llm.calls[0]
    assert "never instructions" in system
    assert '<transcript session="injection">' in user_text


def test_seeded_pii_never_reaches_the_api_boundary_or_fixtures():
    """SI-11 acceptance: every seeded PII value is absent from every string that
    crossed the LLM boundary, and absent from the committed fixture corpus."""
    seeded = [
        "Jane Placeholder",
        "Michael Placeholder",
        "jane.placeholder@example.com",
        "212-555-0187",
        "245 West 98th Street",
    ]
    benign = {
        "rooms_required": [{"program": "bedroom", "count": 3}],
        "adjacency_rules": [],
        "style_tags": ["modern"],
    }
    llm = ScriptedLLM(script=[dict(benign)])
    result = extract_brief(
        [_session("pii_seeded")],
        _opts(client_names=("Jane Placeholder", "Michael Placeholder")),
        llm,
    )

    boundary_text = "\n".join(c.system + "\n" + c.user_text for c in llm.calls)
    for value in seeded:
        assert value not in boundary_text, f"seeded PII crossed the LLM boundary: {value}"
        assert value.lower() not in boundary_text.lower()
    assert result["diagnostics"]["per_session"][0]["pii_redactions"] == {
        "name": 2,
        "email": 1,
        "phone": 1,
        "address": 1,
    }

    # recorded fixtures stay synthetic AND scrubbed: no seeded value may appear in
    # any committed LLM recording or golden brief
    corpus = ""
    for path in [
        *(REPO / "fixtures" / "llm").glob("*.json"),
        *(REPO / "fixtures" / "briefs").glob("*.json"),
    ]:
        corpus += path.read_text()
    for value in seeded:
        assert value not in corpus, f"seeded PII recorded into a fixture: {value}"
