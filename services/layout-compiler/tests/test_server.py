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


def test_furnish_happy_path(monkeypatch):
    from helpers import make_layout

    from layout_compiler.interior_llm import ScriptedInteriorLLM

    proposal = {
        "id": "F-001",
        "kind": "table",
        "revit_family": "CHPT_Nightstand_PLACEHOLDER",
        "revit_type": "Nightstand_450x450_PLACEHOLDER",
        "center": [3500.0, 400.0],
        "rotation_deg": 0.0,
        "footprint": [450.0, 450.0],
    }
    script = [{"furniture": [{"room_id": "R-001", "items": [proposal]}]}]
    monkeypatch.setattr(server, "_interior_llm", lambda: ScriptedInteriorLLM(script=script))
    layout = make_layout()
    res = client.post(
        "/furnish",
        json={
            "project_id": PROJECT_ID,
            "brief": CONFIRMED_BRIEF,
            "commit0_layout": layout,
            "commit1_layout": layout,
            "commit1_ops": [],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert [op["op"] for op in body["ops"]] == ["place_family"]
    assert body["unplaced"] == []
    assert body["svgs"]["furnished"].startswith("<svg")


def test_furnish_error_is_422(monkeypatch):
    from helpers import make_layout

    from layout_compiler.interior_llm import ScriptedInteriorLLM

    monkeypatch.setattr(server, "_interior_llm", lambda: ScriptedInteriorLLM(script=[]))
    unconfirmed = json.loads(json.dumps(CONFIRMED_BRIEF))
    del unconfirmed["meta"]["confirmed_by_client"]
    layout = make_layout()
    res = client.post(
        "/furnish",
        json={
            "project_id": PROJECT_ID,
            "brief": unconfirmed,
            "commit0_layout": layout,
            "commit1_layout": layout,
            "commit1_ops": [],
        },
    )
    assert res.status_code == 422
    assert res.json()["error"] == "brief_not_confirmed"


def test_interior_fixture_llm_requires_the_si7_brief_block(tmp_path):
    from layout_compiler.interior_fixtures import InteriorFixtureLLM

    llm = InteriorFixtureLLM(fixtures_dir=tmp_path)
    try:
        llm.furnish("system", "no data block here", {})
        raise AssertionError("expected the SI-7 structure assertion")
    except AssertionError as err:
        assert "SI-7" in str(err)


def test_interior_fixture_llm_injection_sessions_replay_the_same_golden(tmp_path):
    from layout_compiler.interior_fixtures import InteriorFixtureLLM

    (tmp_path / "furniture_golden_4br.json").write_text(json.dumps({"emission": {"furniture": []}}))
    llm = InteriorFixtureLLM(fixtures_dir=tmp_path)
    golden = llm.furnish("s", '<brief sessions="session1_3br,session2_4br">{}</brief>', {})
    hostile = llm.furnish("s", '<brief sessions="session1_3br,injection">{}</brief>', {})
    assert golden == hostile == {"furniture": []}


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


def test_plan_mep_endpoint_happy_path_and_422():
    from mep_helpers import GOLDEN_CONFIRMATIONS, golden_chain

    g = golden_chain()
    body = {
        "project_id": g["brief"]["meta"]["project_id"],
        "commit0_layout": g["commit0"],
        "commit1_layout": g["commit1_layout"],
        "commit1_ops": g["commit1_ops"],
        "interior_ops": g["interior_ops"],
        "furnished_layout": g["furnished"],
        "placer_wall_ids": g["placer_wall_ids"],
        "confirmations": GOLDEN_CONFIRMATIONS,
    }
    res = client.post("/plan-mep", json=body)
    assert res.status_code == 200, res.text
    plan = res.json()
    assert plan["counts"]["devices"] == 45 and plan["counts"]["stacks"] == 2
    assert plan["svgs"]["mep"].startswith("<svg")
    bad = client.post("/plan-mep", json={**body, "confirmations": {"panel": [5000.0, 3700.0]}})
    assert bad.status_code == 422 and bad.json()["error"] == "panel_not_on_wall"
    unknown = client.post("/plan-mep", json={**body, "surprise": 1})
    assert unknown.status_code == 422  # extra="forbid"
