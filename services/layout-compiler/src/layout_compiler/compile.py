"""Compile orchestration: refuse unconfirmed briefs -> forced emit_layout call
(brief + existing layout as delimited data blocks) -> meta stamping -> the
deterministic validator with a repair loop of AT MOST 2 -> Part G identity diff
(PRE-repair: a mutated frozen element is a hard rejection, never a repair
prompt) -> sim-replay preflight + review-card SVGs -> hard fail preserving the
raw outputs -> REVIEW path (the caller stores the failure)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from chapter_contracts.generated.chapter_layout import ChapterLayout
from revit_sim.model import OpError

from layout_compiler.architectural import DiffError, DiffResult, diff_layouts
from layout_compiler.llm import CompilerLLM
from layout_compiler.prompts import SYSTEM_PROMPT, compile_block, repair_block
from layout_compiler.replay import render_review_svgs
from layout_compiler.schema import emit_tool_schema
from layout_compiler.validator import validate_layout

MAX_REPAIRS = 2  # PLAN.md Phase 4: bounded repair loop (<= 2) -> REVIEW on failure


class CompileError(Exception):
    def __init__(self, code: str, message: str, raw_outputs: list[dict[str, Any]] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.raw_outputs = raw_outputs or []


@dataclass(frozen=True)
class CompileOptions:
    project_id: str
    level_name: str = "Level 1"


def compile_layout(
    brief: dict[str, Any],
    existing_layout: dict[str, Any],
    opts: CompileOptions,
    llm: CompilerLLM,
) -> dict[str, Any]:
    """Returns {"layout", "ops", "demolition", "svgs", "diagnostics"}."""
    if brief.get("meta", {}).get("confirmed_by_client") is not True:
        raise CompileError(
            "brief_not_confirmed",
            "the layout compiler refuses briefs without meta.confirmed_by_client=true "
            "(PLAN.md Part E Phase 4)",
        )
    try:
        ChapterLayout.model_validate(existing_layout)
    except Exception as err:
        raise CompileError(
            "existing_layout_invalid", f"frozen snapshot failed the contract: {err}"
        ) from err

    sessions = ",".join(brief["meta"].get("source_sessions", []))
    user_text = compile_block(
        json.dumps(brief, indent=2), json.dumps(existing_layout, indent=2), sessions
    )
    raw_outputs: list[dict[str, Any]] = []
    attempts = 0
    errors: list[str] = []
    diff: DiffResult | None = None

    while attempts <= MAX_REPAIRS:
        prompt = (
            user_text if not errors else user_text + "\n\n" + repair_block("\n".join(errors[:25]))
        )
        emitted = llm.compile(SYSTEM_PROMPT, prompt, emit_tool_schema())
        raw_outputs.append(emitted)
        candidate = {
            "meta": {
                "project_id": opts.project_id,
                "level": existing_layout["meta"]["level"],
                "units": "mm",
                "origin": "revit_internal_origin",
                "schema_version": "2.3",
                "brief_version": brief["meta"]["brief_version"],
                "phase": "new",
            },
            **{k: v for k, v in emitted.items() if k != "meta"},
        }
        errors = validate_layout(candidate, frozen=existing_layout)
        attempts += 1

        # Part G identity diff on every schema-valid attempt, BEFORE any repair:
        # a moved/renumbered/mutated frozen element is never a repair prompt.
        if not (errors and errors[0].startswith("schema:")):
            try:
                diff = diff_layouts(existing_layout, candidate)
            except DiffError as err:
                raise CompileError(
                    "identity_violation",
                    "Part G identity: " + "; ".join(err.violations[:5]),
                    raw_outputs,
                ) from err

        if not errors:
            assert diff is not None
            try:
                svgs = render_review_svgs(existing_layout, diff.ops)
            except OpError as err:  # defensive: the validator should catch all of these
                raise CompileError("sim_preflight_failed", str(err), raw_outputs) from err
            return {
                "layout": candidate,
                "ops": diff.ops,
                "demolition": diff.demolition,
                "svgs": svgs,
                "diagnostics": {
                    "attempts": attempts,
                    "repair_retried": attempts > 1,
                },
            }

    raise CompileError(
        "layout_invalid",
        f"layout failed the validator after {MAX_REPAIRS} repair retries: " + "; ".join(errors[:5]),
        raw_outputs,
    )
