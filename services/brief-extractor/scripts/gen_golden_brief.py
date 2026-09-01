"""Provenance script for fixtures/briefs/2br_golden_brief.json — the reconciled
brief from the two canonical fixture sessions via the recorded LLM fixtures:

    cd services/brief-extractor && uv run scripts/gen_golden_brief.py

Re-run only when the transcripts, the recorded extractions, or reconciliation
semantics deliberately change."""

from __future__ import annotations

import json
from pathlib import Path

from brief_extractor.extract import ExtractOptions, Session, extract_brief
from brief_extractor.fixtures import FixtureLLM

REPO = Path(__file__).resolve().parents[3]
PROJECT_ID = "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01"
OUT = REPO / "fixtures" / "briefs" / "2br_golden_brief.json"


def main() -> None:
    sessions = [
        Session("session1_3br", (REPO / "fixtures/transcripts/session1_3br.txt").read_text()),
        Session("session2_4br", (REPO / "fixtures/transcripts/session2_4br.txt").read_text()),
    ]
    result = extract_brief(
        sessions, ExtractOptions(project_id=PROJECT_ID, brief_version=1), FixtureLLM()
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result["brief"], indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
