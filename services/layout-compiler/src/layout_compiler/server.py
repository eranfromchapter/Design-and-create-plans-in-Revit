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
from layout_compiler.furnish import FurnishError, FurnishOptions, furnish_layout
from layout_compiler.interior_llm import InteriorLLM
from layout_compiler.llm import CompilerLLM
from layout_compiler.mep.inputs import MepError
from layout_compiler.mep.plan import MepOptions, plan_mep
from layout_compiler.merge.gate import MergeOptions, merge
from layout_compiler.merge.replan import MergeError

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


@cache
def _interior_llm() -> InteriorLLM:
    mode = os.environ.get("LLM_MODE", "fixture")
    if mode == "live":
        from layout_compiler.interior_llm import AnthropicInteriorLLM

        return AnthropicInteriorLLM()
    if mode == "fixture":
        from layout_compiler.interior_fixtures import InteriorFixtureLLM

        return InteriorFixtureLLM()
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


class FurnishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    brief: dict[str, Any]
    commit0_layout: dict[str, Any]
    commit1_layout: dict[str, Any]
    commit1_ops: list[dict[str, Any]]


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


@app.post("/furnish")
def furnish_endpoint(req: FurnishRequest):
    try:
        return furnish_layout(
            req.brief,
            req.commit0_layout,
            req.commit1_layout,
            req.commit1_ops,
            FurnishOptions(project_id=req.project_id),
            _interior_llm(),
        )
    except FurnishError as err:
        return JSONResponse(
            status_code=422,
            content={"error": err.code, "message": err.message, "raw_outputs": err.raw_outputs},
        )


class MepRequest(BaseModel):
    """Phase 6: the gateway sends both frozen snapshots, the committed Commit #1 ops,
    the approved interior branch (ops + furnished layout + placer host walls) and the
    human confirmations from the review card (panel, slab_to_slab_mm)."""

    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    commit0_layout: dict[str, Any]
    commit1_layout: dict[str, Any]
    commit1_ops: list[dict[str, Any]]
    interior_ops: list[dict[str, Any]]
    furnished_layout: dict[str, Any]
    placer_wall_ids: dict[str, str] = Field(default_factory=dict)
    confirmations: dict[str, Any] = Field(default_factory=dict)


@app.post("/plan-mep")
def plan_mep_endpoint(req: MepRequest):
    try:
        return plan_mep(
            req.commit0_layout,
            req.commit1_layout,
            req.commit1_ops,
            req.interior_ops,
            req.furnished_layout,
            req.placer_wall_ids,
            req.confirmations,
            MepOptions(project_id=req.project_id),
        )
    except MepError as err:
        return JSONResponse(
            status_code=422,
            content={"error": err.code, "message": err.message, "raw_outputs": []},
        )


class MergeBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    ops: list[dict[str, Any]] = Field(default_factory=list)
    layout: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)


class MergeRequest(BaseModel):
    """Phase 6 merge gate: the approved interior branch (ops + furnished layout), the
    approved MEP plan, and the chain's iteration state (stateless replay)."""

    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    commit0_layout: dict[str, Any]
    commit1_ops: list[dict[str, Any]]
    interior: MergeBranch
    mep: MergeBranch
    iterations_used: int = Field(default=0, ge=0, le=3)
    iteration: int = Field(default=1, ge=1, le=16)
    prior_actions: list[dict[str, Any]] = Field(default_factory=list)
    clash_pairs: list[dict[str, Any]] = Field(default_factory=list, max_length=256)


@app.post("/merge")
def merge_endpoint(req: MergeRequest):
    try:
        return merge(
            req.commit0_layout,
            req.commit1_ops,
            req.interior.model_dump(),
            req.mep.model_dump(),
            req.iterations_used,
            req.iteration,
            req.prior_actions,
            req.clash_pairs,
            MergeOptions(project_id=req.project_id),
        )
    except MergeError as err:
        return JSONResponse(
            status_code=422,
            content={"error": err.code, "message": err.message, "raw_outputs": []},
        )
