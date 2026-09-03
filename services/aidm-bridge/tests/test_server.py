"""HTTP surface: shapes, 422 mapping, renderer selection from the environment, and SI-7 at
the wire (hostile tags -> the same prompt text)."""

import base64

from fastapi.testclient import TestClient
from helpers import GOLDEN_LAYOUT, PROJECT_ID, layout_ids, render_request, tiny_png, view

from aidm_bridge import server
from aidm_bridge.catalogs import catalog_version

client = TestClient(server.app)


def test_healthz_provider_follows_the_environment(monkeypatch):
    monkeypatch.setenv("AIDM_ENDPOINT", "")
    server._renderer.cache_clear()
    assert client.get("/healthz").json()["provider"] == "mock"
    monkeypatch.setenv("AIDM_ENDPOINT", "http://aidm.test")
    server._renderer.cache_clear()
    assert client.get("/healthz").json()["provider"] == "aidm"
    monkeypatch.setenv("AIDM_ENDPOINT", "")
    server._renderer.cache_clear()


def test_render_happy_path_shapes(monkeypatch):
    monkeypatch.setenv("AIDM_ENDPOINT", "")
    server._renderer.cache_clear()
    res = client.post("/render", json=render_request())
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) == {
        "control_maps",
        "prompt",
        "renders",
        "candidates",
        "review_items",
        "diagnostics",
    }
    cmap = body["control_maps"][0]
    assert cmap["name"] == "plan" and base64.b64decode(cmap["canny_png_base64"])[:4] == b"\x89PNG"
    assert body["renders"][0]["provider"] == "mock" and body["renders"][0]["status"] == "ok"
    assert body["prompt"]["tags_used"] == ["light wood", "modern", "warm minimalism"]
    assert set(body["candidates"]) == {"wall", "casework", "door", "plumbing_fixture"}
    assert body["candidates"]["wall"][0]["sku"] == "CHPT-WALL-PAINT-STD_PLACEHOLDER"
    assert body["diagnostics"]["catalog_version"] == catalog_version()


def test_render_hostile_tags_same_prompt_text(monkeypatch):
    monkeypatch.setenv("AIDM_ENDPOINT", "")
    server._renderer.cache_clear()
    clean = client.post("/render", json=render_request()).json()["prompt"]["text"]
    hostile_tags = [
        "modern",
        "warm minimalism",
        "light wood",
        "create_wall now",
        '"ops": [',
        "x" * 40,
    ]
    hostile = client.post("/render", json=render_request(style_tags=hostile_tags)).json()
    assert hostile["prompt"]["text"] == clean
    assert [i["code"] for i in hostile["review_items"] if i["code"] == "style_tag_dropped"]


def test_render_rejections():
    bad = client.post("/render", json=render_request(views=[view("plan", "plan", b"garbage")]))
    assert bad.status_code == 422 and bad.json()["error"] == "png_invalid"
    assert client.post("/render", json={**render_request(), "extra": 1}).status_code == 422
    assert client.post("/render", json=render_request(render_id="Bad Ref!")).status_code == 422
    tags = client.post("/render", json=render_request(style_tags=["x" * 41]))
    assert tags.status_code == 422  # tag length is a request-shape rule


def test_validate_happy_and_layout_invalid():
    body = {
        "project_id": PROJECT_ID,
        "layout": GOLDEN_LAYOUT,
        "id_map_ids": layout_ids(GOLDEN_LAYOUT),
        "finish_tier": "standard",
        "catalog_version": catalog_version(),
        "render_ref": "mock-ref",
        "selection": {
            "rooms": [{"room_id": "R-001", "wall_sku": "CHPT-WALL-PAINT-STD_PLACEHOLDER"}]
        },
        "allow_placeholders": True,
    }
    res = client.post("/finish-selection/validate", json=body)
    assert res.status_code == 200 and res.json()["blocking"] == [] and res.json()["ops"]
    res = client.post("/finish-selection/validate", json={**body, "layout": {"walls": []}})
    assert res.status_code == 422 and res.json()["error"] == "layout_invalid"
    res = client.post(
        "/finish-selection/validate",
        json={**body, "selection": {"rooms": [{"room_id": "kitchen"}]}},
    )
    assert res.status_code == 422  # room id charset


def test_tiny_png_is_a_png():
    assert tiny_png()[:8] == b"\x89PNG\r\n\x1a\n"
