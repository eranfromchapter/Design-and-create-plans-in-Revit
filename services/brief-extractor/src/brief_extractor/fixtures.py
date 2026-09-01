"""FixtureLLM: replays the SYNTHETIC recorded extractions in fixtures/llm/
(SI-11 — hand-authored, never captured from client data). Used by CI tests, the
CLI's --mock mode, make demo-phase3, and the phase3 e2e converter child. The
session id is parsed from the delimited transcript block, so the fixture used is
exactly the one belonging to the transcript that was sent."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
LLM_FIXTURES_DIR = REPO_ROOT / "fixtures" / "llm"

# session id -> recorded fixture file
RECORDED = {
    "session1_3br": "brief_session1_3br.json",
    "session2_4br": "brief_session2_4br.json",
    "injection": "brief_injection.json",
}

_SESSION_RE = re.compile(r'<transcript session="([^"]+)">')


class FixtureLLM:
    """ExtractorLLM implementation backed by the recorded fixture files."""

    def __init__(self, fixtures_dir: Path = LLM_FIXTURES_DIR):
        self._dir = fixtures_dir
        self.calls: list[tuple[str, str]] = []  # (system, user_text) — boundary record

    def extract(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((system, user_text))
        match = _SESSION_RE.search(user_text)
        if not match:
            raise AssertionError("no transcript block in prompt — SI-7 structure broken")
        session_id = match.group(1)
        filename = RECORDED.get(session_id)
        if filename is None:
            raise AssertionError(f"no recorded fixture for session {session_id!r}")
        return json.loads((self._dir / filename).read_text())["extraction"]
