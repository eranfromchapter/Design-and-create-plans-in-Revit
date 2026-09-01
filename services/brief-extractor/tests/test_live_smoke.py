"""One live smoke behind RUN_LIVE_LLM=1 (PLAN.md Phase 3): the real Anthropic
API, the canonical session-1 transcript, contract-valid output. Never runs in CI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM") != "1",
    reason="live LLM smoke runs only with RUN_LIVE_LLM=1 (never in CI)",
)


def test_live_extraction_smoke():
    from brief_extractor.extract import ExtractOptions, Session, extract_brief
    from brief_extractor.llm import AnthropicLLM

    text = (REPO / "fixtures/transcripts/session1_3br.txt").read_text()
    result = extract_brief(
        [Session("session1_3br", text)],
        ExtractOptions(project_id="1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01", brief_version=1),
        AnthropicLLM(),
    )
    brief = result["brief"]  # extract_brief validated it against the contract already
    bedroom = next(r for r in brief["rooms_required"] if r["program"] == "bedroom")
    assert bedroom["count"] == 3
