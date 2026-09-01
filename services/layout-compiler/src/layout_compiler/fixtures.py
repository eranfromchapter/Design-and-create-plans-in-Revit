"""FixtureLLM: replays the SYNTHETIC recorded layout emission in fixtures/llm/
(SI-11 — authored by scripts/gen_golden_new_layout.py, never captured from
client data). Used by CI tests, the CLI's default mode, make demo-phase4, and
the phase4 e2e compiler child. The sessions attribute of the <brief> block keys
the replay; any session list containing "injection" replays the SAME golden —
hostile brief free-text provably changes nothing about the emitted plan."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
LLM_FIXTURES_DIR = REPO_ROOT / "fixtures" / "llm"

GOLDEN = "layout_golden_4br.json"

# sessions attribute (comma-joined, in order) -> recorded fixture file
RECORDED = {
    "session1_3br,session2_4br": GOLDEN,
}

_SESSIONS_RE = re.compile(r'<brief sessions="([^"]*)">')


class FixtureLLM:
    """CompilerLLM implementation backed by the recorded fixture files."""

    def __init__(self, fixtures_dir: Path = LLM_FIXTURES_DIR):
        self._dir = fixtures_dir
        self.calls: list[tuple[str, str]] = []  # (system, user_text) — boundary record

    def compile(self, system: str, user_text: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((system, user_text))
        match = _SESSIONS_RE.search(user_text)
        if not match:
            raise AssertionError("no <brief sessions=...> block in prompt — SI-7 structure broken")
        sessions = match.group(1)
        if "injection" in sessions.split(","):
            filename = GOLDEN  # hostile transcripts must not change the plan
        else:
            filename = RECORDED.get(sessions)
        if filename is None:
            raise AssertionError(f"no recorded layout fixture for sessions {sessions!r}")
        return json.loads((self._dir / filename).read_text())["emission"]
