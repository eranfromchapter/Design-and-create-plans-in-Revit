"""Injection guard (SI-7 downstream half): whatever the LLM returned, the final
brief must contain ZERO op-registry strings or envelope-shaped fragments — a
hostile transcript trying to launder `create_wall` ops through brief free-text
gets its strings stripped and the attempt is surfaced, never silently passed
downstream to the layout-compiler's prompt."""

from __future__ import annotations

import re
from typing import Any

from brief_extractor.schema import op_registry_names

INJECTION_NOTE = "possible prompt injection in transcript (suspicious content removed)"

_ENVELOPE_SHAPE_RE = re.compile(r'"(?:op|ops|args|envelope_id|payload|sig)"\s*:')


def _op_name_re() -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(map(re.escape, op_registry_names())) + r")\b")


def is_suspicious(text: str) -> bool:
    return bool(_op_name_re().search(text) or _ENVELOPE_SHAPE_RE.search(text))


def scrub_injection(brief_fields: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Remove every string value (list entries, notes, tag strings) that carries
    op-registry names or envelope shapes. Returns (clean fields, hits)."""
    hits = 0

    def clean(value: Any) -> Any:
        nonlocal hits
        if isinstance(value, str):
            if is_suspicious(value):
                hits += 1
                return None
            return value
        if isinstance(value, list):
            out = []
            for item in value:
                cleaned = clean(item)
                if cleaned is not None:
                    out.append(cleaned)
            return out
        if isinstance(value, dict):
            out_d = {}
            for key, item in value.items():
                cleaned = clean(item)
                if cleaned is None:
                    # a required member of a structured entry was hostile:
                    # poison the whole entry rather than emit a hollowed one
                    return None
                out_d[key] = cleaned
            return out_d
        return value

    cleaned_fields: dict[str, Any] = {}
    for key, value in brief_fields.items():
        cleaned = clean(value)
        if cleaned is None:
            # hostile scalar/object at the top level: required fields are all
            # lists (become empty), optional fields are dropped outright
            if isinstance(value, list):
                cleaned_fields[key] = []
            continue
        cleaned_fields[key] = cleaned

    if hits:
        questions = list(cleaned_fields.get("open_questions", []))
        if INJECTION_NOTE not in questions:
            questions.append(INJECTION_NOTE)
        cleaned_fields["open_questions"] = questions[:15]
    return cleaned_fields, hits


def assert_zero_ops(serialized_brief: str) -> None:
    """Test-facing hard predicate: the acceptance suite serializes the final brief
    and asserts this passes."""
    match = _op_name_re().search(serialized_brief)
    if match or _ENVELOPE_SHAPE_RE.search(serialized_brief):
        leaked = match.group(0) if match else "envelope shape"
        raise AssertionError(f"op-registry content leaked into brief: {leaked}")
