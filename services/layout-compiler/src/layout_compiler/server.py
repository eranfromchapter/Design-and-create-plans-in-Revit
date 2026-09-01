"""FastAPI wrapper over compile_layout — the surface the gateway calls
(LAYOUT_COMPILER_URL). LLM selection is an ENV decision made at process start:
LLM_MODE=fixture replays the synthetic recorded emission (CI/e2e/demo);
LLM_MODE=live constructs the real AnthropicLLM (needs ANTHROPIC_API_KEY)."""

from __future__ import annotations

import os
from functools import cache
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from layout_compiler.compile import CompileError, CompileOptions, compile_layout
from layout_compiler.llm import CompilerLLM

app = FastAPI(title="layout-compiler", docs_url=None, redoc_url=None)


@cache
def _llm() -> CompilerLLM:
    mode = os.environ.get("LLM_MODE", "fixture")
    if mode == "live":
        from layout_compiler.llm import AnthropicLLM

        return AnthropicLLM()
    if mode == "fixture":
        from layout_compiler.fixtures import FixtureLLM

        return FixtureLLM()
    raise RuntimeError(f"unknown LLM_MODE {mode!r} (expected 'fixture' or 'live')")


class CompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    brief: dict[str, Any]
    existing_layout: dict[str, Any]


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "llm_mode": os.environ.get("LLM_MODE", "fixture")}


@app.post("/compile")
def compile_endpoint(req: CompileRequest):
    try:
        return compile_layout(
            req.brief, req.existing_layout, CompileOptions(project_id=req.project_id), _llm()
        )
    except CompileError as err:
        # hard fail: the raw outputs ride in the 422 so the caller can store them
        return JSONResponse(
            status_code=422,
            content={"error": err.code, "message": err.message, "raw_outputs": err.raw_outputs},
        )
