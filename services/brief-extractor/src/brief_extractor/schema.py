"""Extraction tool schema, derived from the contract (single source of truth):
brief.v1.json minus `meta` (stamped by the pipeline, not the LLM) and minus
`contradictions` (computed by deterministic reconciliation, never asked of the
model). The LLM is forced onto this tool; its output is then validated against
the schema and, after assembly, against the full ClientBrief contract."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "packages" / "contracts"

PIPELINE_OWNED_FIELDS = ("meta", "contradictions")


@cache
def brief_schema() -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / "schemas" / "brief.v1.json").read_text())


@cache
def extraction_tool_schema() -> dict[str, Any]:
    full = brief_schema()
    properties = {k: v for k, v in full["properties"].items() if k not in PIPELINE_OWNED_FIELDS}
    required = [k for k in full["required"] if k not in PIPELINE_OWNED_FIELDS]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


@cache
def op_registry_names() -> tuple[str, ...]:
    registry = json.loads((CONTRACTS_DIR / "ops" / "registry.json").read_text())
    return tuple(sorted(registry["ops"]))
