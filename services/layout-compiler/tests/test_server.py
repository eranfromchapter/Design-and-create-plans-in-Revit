"""HTTP layer: happy path (scripted LLM), CompileError -> 422 with raw outputs,
request validation, FixtureLLM keying."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from helpers import PROJECT_ID
from test_compile import CONFIRMED_BRIEF, FROZEN, emission

from layout_compiler import server
from layout_compiler.fixtures import FixtureLLM
from layout_compiler.llm import ScriptedLLM

client = TestClient(server.app)


def _compile(monkeypatch, script: list[dict], **overrides):
    monkeypatch.setattr(server, "_llm", lambda: ScriptedLLM(script=script))
    body = {"project_id": PROJECT_ID, "brief": CONFIRMED_BRIEF, "existing_layout": FROZEN}
    body.update(overrides)
    return client.post("/compile", json=body)


def test_healthz_reports_llm_mode():
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["llm_mode"] == "fixture"  # CI default: never a live client


def test_compile_happy_path(monkeypatch):
    res = _compile(monkeypatch, [emission()])
    assert res.status_code == 200
    body = res.json()
    assert body["layout"]["meta"]["phase"] == "new"
    assert body["ops"] == []
    assert body["demolition"] == []
    assert body["svgs"]["new"].startswith("<svg")
    assert body["diagnostics"] == {"attempts": 1, "repair_retried": False}


def test_compile_error_is_422_with_raw_outputs(monkeypatch):
    unconfirmed = json.loads(json.dumps(CONFIRMED_BRIEF))
    del unconfirmed["meta"]["confirmed_by_client"]
    res = _compile(monkeypatch, [emission()], brief=unconfirmed)
    assert res.status_code == 422
    body = res.json()
    assert body["error"] == "brief_not_confirmed"
    assert body["raw_outputs"] == []


def test_request_validation_rejects_unknown_fields(monkeypatch):
    res = _compile(monkeypatch, [emission()], run_ops=True)
    assert res.status_code == 422


def test_fixture_llm_requires_the_si7_brief_block(tmp_path):
    llm = FixtureLLM(fixtures_dir=tmp_path)
    try:
        llm.compile("system", "no data block here", {})
        raise AssertionError("expected the SI-7 structure assertion")
    except AssertionError as err:
        assert "SI-7" in str(err)


def test_fixture_llm_injection_sessions_replay_the_same_golden(tmp_path):
    (tmp_path / "layout_golden_4br.json").write_text(json.dumps({"emission": {"walls": []}}))
    llm = FixtureLLM(fixtures_dir=tmp_path)
    golden = llm.compile("s", '<brief sessions="session1_3br,session2_4br">{}</brief>', {})
    hostile = llm.compile("s", '<brief sessions="session1_3br,injection">{}</brief>', {})
    assert golden == hostile == {"walls": []}
