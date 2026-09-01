"""InteriorFixtureLLM: replays the SYNTHETIC recorded furniture emission in
fixtures/llm/ (SI-11 — authored by scripts/gen_golden_furniture.py, never
captured from client data). Keyed by the <brief sessions="..."> attribute like
the Phase 4 compiler fixture; any session list containing "injection" replays
the SAME golden — hostile brief free-text provably changes nothing."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
LLM_FIXTURES_DIR = REPO_ROOT / "fixtures" / "llm"

FURNITURE_GOLDEN = "furniture_golden_4br.json"

RECORDED = {
    "session1_3br,session2_4br": FURNITURE_GOLDEN,
}

_SESSIONS_RE = re.compile(r'<brief sessions="([^"]*)">')


class InteriorFixtureLLM:
    """InteriorLLM implementation backed by the recorded fixture files."""

    def __init__(self, fixtures_dir: Path = LLM_FIXTURES_DIR):
        self._dir = fixtures_dir
        self.calls: list[tuple[str, str]] = []  # (system, user_text) — boundary record

    def furnish(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((system, user_text))
        match = _SESSIONS_RE.search(user_text)
        if not match:
            raise AssertionError("no <brief sessions=...> block in prompt — SI-7 structure broken")
        sessions = match.group(1)
        if "injection" in sessions.split(","):
            filename = FURNITURE_GOLDEN  # hostile transcripts must not change the plan
        else:
            filename = RECORDED.get(sessions)
        if filename is None:
            raise AssertionError(f"no recorded furniture fixture for sessions {sessions!r}")
        return json.loads((self._dir / filename).read_text())["emission"]
