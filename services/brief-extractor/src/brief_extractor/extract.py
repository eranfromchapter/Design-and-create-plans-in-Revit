"""Pipeline orchestration: normalize -> per-session tool-enforced extraction
(ONE repair retry, then hard fail with the raw outputs preserved) -> deterministic
cross-session reconciliation -> injection guard -> meta stamping -> contract
validation. The returned brief is schema-valid or ExtractError is raised."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import jsonschema
from chapter_contracts.generated.brief import ClientBrief

from brief_extractor.guard import scrub_injection
from brief_extractor.llm import ExtractorLLM
from brief_extractor.normalize import normalize_transcript
from brief_extractor.prompts import SYSTEM_PROMPT, repair_block, transcript_block
from brief_extractor.reconcile import reconcile
from brief_extractor.schema import brief_schema, extraction_tool_schema


class ExtractError(Exception):
    def __init__(self, code: str, message: str, raw_outputs: list[dict[str, Any]] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        # the failed raw outputs are PRESERVED (stored by the caller / returned in
        # the 422 body) — "hard fail with stored raw output" per the acceptance
        self.raw_outputs = raw_outputs or []


@dataclass(frozen=True)
class Session:
    session_id: str
    text: str


@dataclass(frozen=True)
class ExtractOptions:
    project_id: str
    brief_version: int
    client_names: tuple[str, ...] = ()
    prior_brief: dict[str, Any] | None = None  # previous version's full ClientBrief


@dataclass
class Diagnostics:
    per_session: list[dict[str, Any]] = field(default_factory=list)
    injection_hits: int = 0
    notes: list[str] = field(default_factory=list)


def _validate_extraction(candidate: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(extraction_tool_schema())
    return [
        f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(candidate), key=lambda e: str(e.path))
    ]


def _extract_session(
    llm: ExtractorLLM, session: Session, diagnostics: Diagnostics, client_names: tuple[str, ...]
) -> dict[str, Any]:
    normalized = normalize_transcript(session.text, list(client_names))
    user_text = transcript_block(session.session_id, normalized.text)
    raw_outputs: list[dict[str, Any]] = []

    candidate = llm.extract(SYSTEM_PROMPT, user_text, extraction_tool_schema())
    raw_outputs.append(candidate)
    errors = _validate_extraction(candidate)
    if errors:
        repair_text = user_text + "\n\n" + repair_block("\n".join(errors[:20]))
        candidate = llm.extract(SYSTEM_PROMPT, repair_text, extraction_tool_schema())
        raw_outputs.append(candidate)
        errors = _validate_extraction(candidate)
        if errors:
            raise ExtractError(
                "extraction_invalid",
                f"session {session.session_id}: output failed contract validation "
                f"after one repair retry: {'; '.join(errors[:5])}",
                raw_outputs,
            )

    diagnostics.per_session.append(
        {
            "session_id": session.session_id,
            "dropped_chitchat_lines": normalized.dropped_lines,
            "pii_redactions": normalized.scrub.counts,
            "repair_retried": len(raw_outputs) > 1,
        }
    )
    return candidate


def extract_brief(
    sessions: list[Session], opts: ExtractOptions, llm: ExtractorLLM
) -> dict[str, Any]:
    """Returns {"brief": <ClientBrief dict>, "diagnostics": {...}}."""
    if not sessions:
        raise ExtractError("no_sessions", "at least one session transcript is required")

    diagnostics = Diagnostics()
    contradictions: list[dict[str, str]] = []
    prior = opts.prior_brief or {}
    # the prior brief version is the reconciliation baseline; its recorded
    # contradictions carry forward
    accumulated = {k: v for k, v in prior.items() if k not in ("meta", "contradictions")}
    contradictions.extend(prior.get("contradictions", []))

    # session order in the request IS the chronology: later entries win
    for session in sessions:
        extraction = _extract_session(llm, session, diagnostics, opts.client_names)
        accumulated = reconcile(accumulated, extraction, contradictions, diagnostics.notes)

    accumulated, hits = scrub_injection(accumulated)
    diagnostics.injection_hits = hits

    source_sessions = [
        *prior.get("meta", {}).get("source_sessions", []),
        *[s.session_id for s in sessions],
    ]
    brief: dict[str, Any] = {
        "meta": {
            "project_id": opts.project_id,
            "brief_version": opts.brief_version,
            "source_sessions": source_sessions,
        },
        **accumulated,
    }
    if contradictions:
        brief["contradictions"] = contradictions[:20]

    try:
        ClientBrief.model_validate(brief)
        jsonschema.validate(brief, brief_schema(), format_checker=jsonschema.FormatChecker())
    except Exception as err:
        raise ExtractError(
            "brief_invalid",
            f"assembled brief failed contract validation: {err}",
            [brief],
        ) from err

    return {
        "brief": brief,
        "diagnostics": {
            "per_session": diagnostics.per_session,
            "injection_hits": diagnostics.injection_hits,
            "notes": diagnostics.notes,
            "contradiction_count": len(brief.get("contradictions", [])),
        },
    }


def contradiction_diff(brief: dict[str, Any]) -> str:
    """Human-readable contradiction summary for the demo/CLI."""
    rows = brief.get("contradictions", [])
    if not rows:
        return "no contradictions recorded"
    lines = ["contradictions:"]
    for row in rows:
        lines.append(
            f"  {row['field']}: {row['earlier']!r} -> {row['later']!r} ({row['resolution']})"
        )
    return "\n".join(lines)
