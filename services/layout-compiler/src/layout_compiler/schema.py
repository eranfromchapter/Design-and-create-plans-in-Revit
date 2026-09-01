"""Tool schema for the forced emit_layout call: the layout contract minus `meta`
(stamped by the pipeline from the brief/project, never the LLM's business)."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from layout_compiler.catalogs import CONTRACTS_DIR

PIPELINE_OWNED_FIELDS = ("meta",)


@cache
def layout_schema() -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / "schemas" / "chapter-layout.v2.3.json").read_text())


@cache
def emit_tool_schema() -> dict[str, Any]:
    full = layout_schema()
    properties = {k: v for k, v in full["properties"].items() if k not in PIPELINE_OWNED_FIELDS}
    required = [k for k in full["required"] if k not in PIPELINE_OWNED_FIELDS]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
        "$defs": full.get("$defs", {}),
    }
