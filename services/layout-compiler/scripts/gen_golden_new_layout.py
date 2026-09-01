"""Writes the recorded compiler fixture from the golden_4br table
(fixtures/llm/layout_golden_4br.json). Run from anywhere:

  uv run python scripts/gen_golden_new_layout.py

test_fixture_drift.py fails if the committed file drifts from the table."""

from __future__ import annotations

import json

from layout_compiler.golden_4br import REPO_ROOT, emission

OUT = REPO_ROOT / "fixtures" / "llm" / "layout_golden_4br.json"


def main() -> None:
    OUT.write_text(json.dumps({"emission": emission()}, indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
