"""The committed recorded fixture must match its generator table exactly
(scan-converter precedent: fixtures are authored by code, pinned by bytes)."""

from __future__ import annotations

import json

from layout_compiler.golden_4br import REPO_ROOT, emission


def test_committed_fixture_matches_generator():
    committed = json.loads((REPO_ROOT / "fixtures" / "llm" / "layout_golden_4br.json").read_text())
    assert committed == {"emission": emission()}
