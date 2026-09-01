"""HTTP layer: fixture-mode extraction, ExtractError -> 422 with raw outputs,
request validation."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from brief_extractor.server import app

REPO = Path(__file__).resolve().parents[3]
PROJECT_ID = "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01"

client = TestClient(app)


def _extract(sessions: list[dict], **overrides):
    body = {"project_id": PROJECT_ID, "brief_version": 1, "sessions": sessions}
    body.update(overrides)
    return client.post("/extract", json=body)


def test_healthz_reports_llm_mode():
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["llm_mode"] == "fixture"  # CI default: never a live client


def test_extract_happy_path_fixture_mode():
    text = (REPO / "fixtures/transcripts/session1_3br.txt").read_text()
    res = _extract([{"session_id": "session1_3br", "text": text}])
    assert res.status_code == 200
    brief = res.json()["brief"]
    assert brief["meta"]["brief_version"] == 1
    assert any(r["program"] == "bedroom" and r["count"] == 3 for r in brief["rooms_required"])


def test_unknown_session_never_fabricates_a_brief():
    # FixtureLLM refuses sessions it has no recording for; the server must surface
    # that as a hard error, never a fabricated brief
    import pytest

    with pytest.raises(AssertionError, match="no recorded fixture"):
        _extract([{"session_id": "nonexistent", "text": "hello kitchen"}])


def test_request_validation_rejects_unknown_fields():
    text = (REPO / "fixtures/transcripts/session1_3br.txt").read_text()
    res = _extract([{"session_id": "session1_3br", "text": text}], run_ops=True)
    assert res.status_code == 422
