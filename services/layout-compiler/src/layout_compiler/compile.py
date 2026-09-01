"""Compile orchestration: refuse unconfirmed briefs -> forced emit_layout call
(brief + existing layout as delimited data blocks) -> meta stamping -> the
deterministic validator with a repair loop of AT MOST 2 -> hard fail preserving
the raw outputs -> REVIEW path (the caller stores the failure)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from chapter_contracts.generated.chapter_layout import ChapterLayout

from layout_compiler.llm import CompilerLLM
from layout_compiler.prompts import SYSTEM_PROMPT, compile_block, repair_block
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
    """Returns {"layout": <valid ChapterLayout dict>, "diagnostics": {...}}."""
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

    user_text = compile_block(json.dumps(brief, indent=2), json.dumps(existing_layout, indent=2))
    raw_outputs: list[dict[str, Any]] = []
    attempts = 0
    errors: list[str] = []
    candidate: dict[str, Any] = {}

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
        errors = validate_layout(candidate)
        attempts += 1
        if not errors:
            return {
                "layout": candidate,
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
