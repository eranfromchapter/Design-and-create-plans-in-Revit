"""Small builders for the bridge tests: a synthetic PNG, the golden layout, id lists."""

from __future__ import annotations

import base64
import json
from typing import Any

import cv2
import numpy as np

from aidm_bridge.golden_render import REPO_ROOT

GOLDEN_LAYOUT: dict[str, Any] = json.loads(
    (REPO_ROOT / "fixtures" / "goldens" / "phase6_2br_mep.json").read_text()
)["layout"]
PROJECT_ID = "6f1c2a3e-9b4d-4c5e-8f70-123456789abc"


def layout_ids(layout: dict[str, Any]) -> list[str]:
    ids = [w["id"] for w in layout["walls"]]
    ids += [d["id"] for d in layout["doors"]] + [n["id"] for n in layout.get("windows", [])]
    ids += [k["id"] for k in layout.get("casework", []) or []]
    for group in layout.get("furniture", []):
        ids += [item["id"] for item in group["items"]]
    return sorted(ids)


def tiny_png(width: int = 96, height: int = 96, *, rgba: bool = True, stroke: bool = True) -> bytes:
    """A transparent (or white) canvas with a black rectangle outline — the shape of the sim's
    resvg output (black strokes on transparent RGBA)."""
    if rgba:
        img = np.zeros((height, width, 4), np.uint8)
        if stroke:
            cv2.rectangle(img, (16, 16), (width - 17, height - 17), (0, 0, 0, 255), 3)
    else:
        img = np.full((height, width, 3), 255, np.uint8)
        if stroke:
            cv2.rectangle(img, (16, 16), (width - 17, height - 17), (0, 0, 0), 3)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def view(name: str, kind: str, png: bytes, px: int = 256) -> dict[str, Any]:
    return {"name": name, "kind": kind, "px": px, "png_base64": b64(png)}


def render_request(**overrides: Any) -> dict[str, Any]:
    req = {
        "project_id": PROJECT_ID,
        "render_id": "test-render",
        "views": [view("plan", "plan", tiny_png())],
        "style_tags": ["modern", "warm minimalism", "light wood"],
        "finish_tier": "standard",
        "rooms": [{"id": "R-001", "name": "Bedroom 1", "program": "bedroom"}],
        "allow_placeholders": True,
    }
    req.update(overrides)
    return req
