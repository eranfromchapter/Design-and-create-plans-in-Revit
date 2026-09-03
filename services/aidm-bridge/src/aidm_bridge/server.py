"""FastAPI wrapper over render_views and validate_selection — the surface the gateway calls
(AIDM_BRIDGE_URL). Renderer selection is an ENV decision made at process start: an empty
AIDM_ENDPOINT selects the deterministic MockRenderer (CI/e2e/demo); a set endpoint selects
the HttpRenderer (AIDM_API_KEY optional). This module is the bridge's ONLY environment reader."""

from __future__ import annotations

import os
from functools import cache
from typing import Annotated, Any, Literal

import cv2
from chapter_contracts.generated.brief import FinishTier
from chapter_contracts.generated.chapter_layout import ChapterLayout, Program
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from aidm_bridge.aidm import HttpRenderer, MockRenderer, Renderer
from aidm_bridge.render import RenderError, RenderOptions, render_views
from aidm_bridge.selection import SelectionError, validate_selection

app = FastAPI(title="aidm-bridge", docs_url=None, redoc_url=None)

PROJECT_ID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
REF_RE = r"^[a-z0-9][a-z0-9_-]{0,63}$"  # the wss-messages blobRef charset
ELEMENT_ID_RE = r"^[A-Z]{1,2}-[0-9]{2,4}$"
ROOM_ID_RE = r"^R-[0-9]{3}$"
MAX_PNG_B64_CHARS = 22_400_000  # about 16 MiB decoded


@cache
def _renderer() -> Renderer:
    endpoint = os.environ.get("AIDM_ENDPOINT", "").strip()
    if endpoint:
        return HttpRenderer(endpoint, os.environ.get("AIDM_API_KEY") or None)
    return MockRenderer()


def _error(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": code, "message": message, "raw_outputs": []}
    )


class ViewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=REF_RE)
    kind: Literal["plan", "section", "3d_hidden"]
    px: int = Field(ge=256, le=4096)
    png_base64: str = Field(min_length=1, max_length=MAX_PNG_B64_CHARS)


class RoomIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=ROOM_ID_RE)
    name: str = Field(min_length=1, max_length=120)
    program: Program


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(pattern=PROJECT_ID_RE)
    render_id: str = Field(pattern=REF_RE)
    views: list[ViewIn] = Field(min_length=1, max_length=20)
    style_tags: list[Annotated[str, StringConstraints(max_length=40)]] = Field(
        default_factory=list, max_length=12
    )
    finish_tier: FinishTier = FinishTier.standard
    rooms: list[RoomIn] = Field(default_factory=list, max_length=60)
    allow_placeholders: bool = False


class SelectionRoom(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_id: str = Field(pattern=ROOM_ID_RE)
    wall_sku: str | None = Field(default=None, min_length=1, max_length=80)


class SelectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=ELEMENT_ID_RE)
    sku: str = Field(min_length=1, max_length=80)


class Override(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(pattern=r"^[A-Z]{1,2}-[0-9]{2,4}$")
    sku: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=3, max_length=300)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rooms: list[SelectionRoom] = Field(default_factory=list, max_length=60)
    casework: list[SelectionItem] = Field(default_factory=list, max_length=80)
    doors: list[SelectionItem] = Field(default_factory=list, max_length=120)
    plumbing_fixtures: list[SelectionItem] = Field(default_factory=list, max_length=60)
    overrides: list[Override] = Field(default_factory=list, max_length=64)


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(pattern=PROJECT_ID_RE)
    layout: dict[str, Any]
    id_map_ids: list[str] = Field(max_length=4000)
    finish_tier: FinishTier
    catalog_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(-[a-z0-9.-]+)?$")
    render_ref: str | None = Field(default=None, pattern=REF_RE)
    selection: Selection
    allow_placeholders: bool = False


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "provider": _renderer().provider, "opencv": cv2.__version__}


@app.post("/render")
def render(req: RenderRequest) -> JSONResponse:
    try:
        result = render_views(
            req.model_dump(mode="json"),
            _renderer(),
            RenderOptions(project_id=req.project_id, allow_placeholders=req.allow_placeholders),
        )
    except RenderError as err:
        return _error(err.code, err.message)
    return JSONResponse(status_code=200, content=result)


@app.post("/finish-selection/validate")
def finish_selection_validate(req: ValidateRequest) -> JSONResponse:
    try:
        ChapterLayout.model_validate(req.layout)
    except ValidationError as err:
        return _error("layout_invalid", str(err)[:2000])
    try:
        result = validate_selection(
            req.layout,
            req.id_map_ids,
            req.finish_tier.value,
            req.catalog_version,
            req.render_ref,
            req.selection.model_dump(mode="json"),
            req.allow_placeholders,
        )
    except SelectionError as err:
        return _error(err.code, err.message)
    return JSONResponse(status_code=200, content=result)
