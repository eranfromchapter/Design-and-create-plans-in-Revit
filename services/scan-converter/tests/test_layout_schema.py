"""Converter output is contract-valid: pydantic strict model (extra=forbid,
no-defaults) AND the raw JSON schema both accept the emitted layout; the golden
layout JSON is pinned semantically."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from chapter_contracts.generated.chapter_layout import ChapterLayout

from scan_converter.lane_a import convert

REPO = Path(__file__).resolve().parents[3]
SCHEMA = json.loads(
    (REPO / "packages" / "contracts" / "schemas" / "chapter-layout.v2.3.json").read_text()
)
GOLDEN = REPO / "fixtures" / "layouts" / "2br_golden.json"


def test_layout_validates_against_pydantic_and_jsonschema(fixture_mm_bytes, opts):
    layout = convert(fixture_mm_bytes, opts)["layout"]
    ChapterLayout.model_validate(layout)
    jsonschema.validate(layout, SCHEMA, format_checker=jsonschema.FormatChecker())
    assert layout["meta"]["phase"] == "existing"
    assert layout["meta"]["scan"] == {"source": "polycam", "capture": "floorplan_dxf"}
    assert layout["rooms"] == [] and layout["furniture"] == []
    assert all(w["source"] == "scan" for w in layout["walls"])


def test_golden_layout_json(fixture_mm_bytes, opts):
    """Semantic golden: the converter's full output for the canonical fixture.
    Regenerate deliberately with scripts/gen_golden_layout.py after geometry
    changes, and re-eyeball the Phase 2 SVG golden."""
    layout = convert(fixture_mm_bytes, opts)["layout"]
    assert layout == json.loads(GOLDEN.read_text())
