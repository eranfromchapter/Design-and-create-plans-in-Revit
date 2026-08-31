"""FastAPI wrapper over lane_a.convert — the surface the gateway calls
(SCAN_CONVERTER_URL). Stateless; every rejection maps to 422 {error, message}."""

from __future__ import annotations

import base64
import binascii
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from scan_converter.lane_a import ConvertError, ConvertOptions, convert

app = FastAPI(title="scan-converter", docs_url=None, redoc_url=None)


class ConvertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dxf_base64: str = Field(min_length=1)
    project_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    level_name: str = Field(default="Level 1", min_length=1, max_length=80)
    # create_wall height bounds (registry): out-of-range defaults would only fail later
    ceiling_default_mm: float = Field(default=2700.0, ge=2100, le=6000)
    unit_override: Literal["mm", "inch", "ft", "cm", "m"] | None = None
    cloud_ref: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/convert")
def convert_endpoint(req: ConvertRequest):
    try:
        dxf_bytes = base64.b64decode(req.dxf_base64, validate=True)
    except (binascii.Error, ValueError):
        return JSONResponse(
            status_code=422,
            content={"error": "dxf_parse_error", "message": "dxf_base64 is not valid base64"},
        )
    opts = ConvertOptions(
        project_id=req.project_id,
        level_name=req.level_name,
        ceiling_default_mm=req.ceiling_default_mm,
        unit_override=req.unit_override,
        cloud_ref=req.cloud_ref,
    )
    try:
        return convert(dxf_bytes, opts)
    except ConvertError as err:
        return JSONResponse(status_code=422, content={"error": err.code, "message": err.message})
