"""Furnish orchestration (Phase 5): refuse unconfirmed briefs -> forced
emit_furniture call (brief + approved layout + capacity hints as delimited data
blocks) -> proposal validation with a repair loop of AT MOST 2 (schema /
catalog / referential / duplicate-id errors ONLY) -> catalog normalization ->
the deterministic Part G placer (placement infeasibility is REVIEW content,
NEVER a repair) -> full-validator oracle on the furnished layout -> place ops
+ review-card SVGs.

Wall-clock lives ONLY here, at the request boundary: FURNISH_TIME_LIMIT_S
expiry is a hard 422, never a partial or machine-dependent result.

PHASE 6 HANDOFF CONTRACT (the merge gate consumes this run's gateway review):
- the LATEST review of kind "interior_plan" must be status=approved, else 409;
- content.ops verbatim is the interior half of Commit #2, under
  {review_id, content_hash} as the interior approval reference;
- content.layout.furniture seeds the MEP agent (kind/fixture_units/hookups);
- content.unplaced items (full proposals, hookups included) are EXCLUDED from
  Commit #2 and do NOT seed MEP."""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from typing import Any

import jsonschema
from chapter_contracts.generated.chapter_layout import ChapterLayout

from layout_compiler.catalogs import family_types, new_families
from layout_compiler.furnish_hints import capacity_hints
from layout_compiler.interior import legalize_furniture
from layout_compiler.interior_llm import InteriorLLM
from layout_compiler.interior_ops import furniture_ops
from layout_compiler.interior_prompts import (
    FURNISH_SYSTEM_PROMPT,
    furnish_block,
    furnish_repair_block,
)
from layout_compiler.interior_schema import furnish_tool_schema
from layout_compiler.replay import render_furnish_svgs
from layout_compiler.validator import validate_layout

MAX_FURNISH_REPAIRS = 2  # SI-6: bounded repair loop (<= 2) -> REVIEW on failure
FURNISH_TIME_LIMIT_S = 60.0  # request boundary only; tests monkeypatch this


class FurnishError(Exception):
    def __init__(self, code: str, message: str, raw_outputs: list[dict[str, Any]] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.raw_outputs = raw_outputs or []


@dataclass(frozen=True)
class FurnishOptions:
    project_id: str


def _proposal_errors(emitted: dict[str, Any], layout: dict[str, Any]) -> list[str]:
    """Repairable proposal problems: schema, referential, catalog, duplicates.
    Placement infeasibility is NOT here — it is REVIEW content, never a repair."""
    try:
        jsonschema.validate(emitted, furnish_tool_schema())
    except jsonschema.ValidationError as err:
        return [f"schema: {str(err).splitlines()[0][:300]}"]

    errors: list[str] = []
    room_ids = {r["id"] for r in layout["rooms"]}
    element_ids = {
        e["id"] for group in ("walls", "doors", "windows", "rooms") for e in layout[group]
    }
    seen: set[str] = set()
    for entry in emitted["furniture"]:
        if entry["room_id"] not in room_ids:
            errors.append(f"furniture.{entry['room_id']}: unknown room")
        for item in entry["items"]:
            if item["id"] in seen or item["id"] in element_ids:
                errors.append(f"furniture.{item['id']}: duplicate element id")
            seen.add(item["id"])
            if item["revit_family"] not in new_families():
                errors.append(
                    f"furniture.{item['id']}: revit_family {item['revit_family']!r} not in "
                    "new_construction_types.json families (closed vocabulary)"
                )
                continue
            spec = family_types().get((item["revit_family"], item["revit_type"]))
            if spec is None:
                errors.append(
                    f"furniture.{item['id']}: revit_type {item['revit_type']!r} is not a "
                    f"catalog type of {item['revit_family']!r}"
                )
                continue
            if item["kind"] not in spec["kinds"]:
                errors.append(
                    f"furniture.{item['id']}: kind {item['kind']!r} not offered by "
                    f"{item['revit_family']!r}"
                )
    return sorted(errors)


def furnish_layout(
    brief: dict[str, Any],
    commit0_layout: dict[str, Any],
    commit1_layout: dict[str, Any],
    commit1_ops: list[dict[str, Any]],
    opts: FurnishOptions,
    llm: InteriorLLM,
) -> dict[str, Any]:
    """Returns {"layout", "ops", "svgs": {commit1, furnished}, "unplaced",
    "diagnostics"}. Raises FurnishError on every failure path."""
    started = time.monotonic()
    if brief.get("meta", {}).get("confirmed_by_client") is not True:
        raise FurnishError(
            "brief_not_confirmed",
            "the interior agent refuses briefs without meta.confirmed_by_client=true",
        )
    try:
        ChapterLayout.model_validate(commit1_layout)
    except Exception as err:
        raise FurnishError(
            "commit1_layout_invalid", f"approved layout failed the contract: {err}"
        ) from err

    sessions = ",".join(brief["meta"].get("source_sessions", []))
    user_text = furnish_block(
        json.dumps(brief, indent=2),
        json.dumps(commit1_layout, indent=2),
        json.dumps(capacity_hints(commit1_layout), indent=2),
        sessions,
    )

    raw_outputs: list[dict[str, Any]] = []
    attempts = 0
    errors: list[str] = []
    emitted: dict[str, Any] = {}
    while attempts <= MAX_FURNISH_REPAIRS:
        prompt = (
            user_text
            if not errors
            else user_text + "\n\n" + furnish_repair_block("\n".join(errors[:25]))
        )
        emitted = llm.furnish(FURNISH_SYSTEM_PROMPT, prompt, furnish_tool_schema())
        raw_outputs.append(emitted)
        attempts += 1
        if time.monotonic() - started > FURNISH_TIME_LIMIT_S:
            raise FurnishError(
                "furnish_timeout",
                f"furnish exceeded {FURNISH_TIME_LIMIT_S:.0f}s at the request boundary",
                raw_outputs,
            )
        errors = _proposal_errors(emitted, commit1_layout)
        if not errors:
            break
    else:
        raise FurnishError(
            "proposal_invalid",
            f"furniture proposal failed validation after {MAX_FURNISH_REPAIRS} repair "
            "retries: " + "; ".join(errors[:5]),
            raw_outputs,
        )

    proposals = [
        {**item, "room_id": entry["room_id"]}
        for entry in emitted["furniture"]
        for item in entry["items"]
    ]
    outcome = legalize_furniture(proposals, commit1_layout)
    if time.monotonic() - started > FURNISH_TIME_LIMIT_S:
        raise FurnishError(
            "furnish_timeout",
            f"furnish exceeded {FURNISH_TIME_LIMIT_S:.0f}s at the request boundary",
            raw_outputs,
        )

    furnished = copy.deepcopy(commit1_layout)
    furnished["furniture"] = outcome.furniture
    oracle = validate_layout(furnished)
    if oracle:
        raise FurnishError(
            "furnish_internal",
            "the placer emitted a layout the validator rejects (bug): " + "; ".join(oracle[:5]),
            raw_outputs,
        )

    ops = furniture_ops(outcome.furniture, commit1_layout["meta"]["level"])
    svgs = render_furnish_svgs(commit0_layout, commit1_ops, ops)
    return {
        "layout": furnished,
        "ops": ops,
        "svgs": svgs,
        "unplaced": outcome.unplaced,
        "diagnostics": {
            "attempts": attempts,
            "repair_retried": attempts > 1,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            **outcome.diagnostics,
        },
    }
