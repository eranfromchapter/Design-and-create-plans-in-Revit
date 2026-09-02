"""FastAPI wrapper over extract_brief — the surface the gateway calls
(BRIEF_EXTRACTOR_URL). LLM selection is an ENV decision made at process start:
LLM_MODE=fixture replays the synthetic recordings (CI/e2e/demo);
LLM_MODE=live constructs the real AnthropicLLM (needs ANTHROPIC_API_KEY)."""

from __future__ import annotations

import os
from functools import cache
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from brief_extractor.extract import ExtractError, ExtractOptions, Session, extract_brief
from brief_extractor.llm import ExtractorLLM

app = FastAPI(title="brief-extractor", docs_url=None, redoc_url=None)


@cache
def _llm() -> ExtractorLLM:
    mode = os.environ.get("LLM_MODE", "fixture")
    if mode == "live":
        from brief_extractor.llm import AnthropicLLM

        return AnthropicLLM()
    if mode == "fixture":
        from brief_extractor.fixtures import FixtureLLM

        return FixtureLLM()
    raise RuntimeError(f"unknown LLM_MODE {mode!r} (expected 'fixture' or 'live')")


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # safe charset only: session ids become structural prompt markup (SI-7)
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,120}$")
    text: str = Field(min_length=1)


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    brief_version: int = Field(ge=1)
    sessions: list[SessionIn] = Field(min_length=1, max_length=20)
    client_names: list[str] = Field(default_factory=list, max_length=10)
    prior_brief: dict[str, Any] | None = None


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "llm_mode": os.environ.get("LLM_MODE", "fixture")}


@app.post("/extract")
def extract_endpoint(req: ExtractRequest):
    opts = ExtractOptions(
        project_id=req.project_id,
        brief_version=req.brief_version,
        client_names=tuple(req.client_names),
        prior_brief=req.prior_brief,
    )
    try:
        return extract_brief([Session(s.session_id, s.text) for s in req.sessions], opts, _llm())
    except ExtractError as err:
        # hard fail: the raw outputs ride in the 422 so the caller can store them
        return JSONResponse(
            status_code=422,
            content={"error": err.code, "message": err.message, "raw_outputs": err.raw_outputs},
        )
