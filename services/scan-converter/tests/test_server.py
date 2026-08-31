"""HTTP layer: request validation, ConvertError -> 422 {error, message}, happy path."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from helpers import PROJECT_ID, add_wall, doc_bytes, empty_doc

from scan_converter.server import app

client = TestClient(app)


def _post(dxf: bytes, **overrides):
    body = {"dxf_base64": base64.b64encode(dxf).decode(), "project_id": PROJECT_ID}
    body.update(overrides)
    return client.post("/convert", json=body)


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_convert_happy_path(fixture_mm_bytes):
    res = _post(fixture_mm_bytes, ceiling_default_mm=2600)
    assert res.status_code == 200
    body = res.json()
    assert body["review_payload"]["counts"] == {"walls": 17, "doors": 5, "windows": 3}
    assert all(w["height"] == 2600.0 for w in body["layout"]["walls"])
    assert body["layout"]["meta"]["project_id"] == PROJECT_ID


def test_cloud_ref_lands_in_scan_meta(fixture_mm_bytes):
    res = _post(fixture_mm_bytes, cloud_ref="poly-cloud-001")
    assert res.json()["layout"]["meta"]["scan"]["cloud_ref"] == "poly-cloud-001"


def test_convert_error_maps_to_422():
    doc = empty_doc()
    add_wall(doc, [(0, 0), (8000, 0)], width=0)
    res = _post(doc_bytes(doc))
    assert res.status_code == 422
    assert res.json()["error"] == "profile_violation"


def test_bad_base64_is_422():
    res = client.post("/convert", json={"dxf_base64": "@@@", "project_id": PROJECT_ID})
    assert res.status_code == 422
    assert res.json()["error"] == "dxf_parse_error"


def test_request_validation_rejects_unknown_fields(fixture_mm_bytes):
    res = _post(fixture_mm_bytes, rescale_to=42)
    assert res.status_code == 422


def test_ceiling_bounds_enforced(fixture_mm_bytes):
    assert _post(fixture_mm_bytes, ceiling_default_mm=1000).status_code == 422
