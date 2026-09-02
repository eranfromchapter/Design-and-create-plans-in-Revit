"""Tool schema for the forced emit_furniture call: the contract's furniture
subtree verbatim (plus the full $defs — pt2/size2 refs must resolve). The LLM
emits ONLY furniture; walls/doors/rooms are data blocks, never re-emitted, so
the Part G 1mm-echo failure class cannot exist here."""

from __future__ import annotations

from functools import cache
from typing import Any

from layout_compiler.schema import layout_schema


@cache
def furnish_tool_schema() -> dict[str, Any]:
    full = layout_schema()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["furniture"],
        "properties": {"furniture": full["properties"]["furniture"]},
        "$defs": full.get("$defs", {}),
    }
