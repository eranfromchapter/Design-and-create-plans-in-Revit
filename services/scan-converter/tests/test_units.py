"""Phase 2 acceptance: inches vs mm identical; $INSUNITS=0 -> heuristic + required
review-card confirmation; span outside every band -> unit_undetectable."""

from __future__ import annotations

import pytest
from helpers import PROJECT_ID, add_wall, doc_bytes, empty_doc

from scan_converter.lane_a import ConvertError, ConvertOptions, convert


def test_mm_and_inch_variants_produce_identical_layouts(fixture_mm_bytes, fixture_inch_bytes, opts):
    mm = convert(fixture_mm_bytes, opts)
    inch = convert(fixture_inch_bytes, opts)
    assert mm["layout"] == inch["layout"]
    unit = inch["review_payload"]["unit"]
    assert unit["detected"] == "inch"
    assert unit["source"] == "insunits"
    assert unit["confirmation_required"] is False
    assert unit["bbox_span_mm"] == 11400.0


def test_unitless_requires_confirmation(fixture_unitless_bytes, fixture_mm_bytes, opts):
    result = convert(fixture_unitless_bytes, opts)
    unit = result["review_payload"]["unit"]
    assert unit["detected"] == "mm"
    assert unit["source"] == "heuristic"
    assert unit["confirmation_required"] is True
    assert result["layout"] == convert(fixture_mm_bytes, opts)["layout"]


def test_unitless_inch_scale_heuristic(opts):
    doc = empty_doc(insunits=0)
    add_wall(doc, [(0, 0), (450, 0)], width=4)  # 450 raw units -> inch band
    unit = convert(doc_bytes(doc), opts)["review_payload"]["unit"]
    assert unit["detected"] == "inch"
    assert unit["confirmation_required"] is True


def test_unit_override_wins_without_confirmation(fixture_unitless_bytes):
    opts = ConvertOptions(project_id=PROJECT_ID, unit_override="mm")
    unit = convert(fixture_unitless_bytes, opts)["review_payload"]["unit"]
    assert unit["source"] == "override"
    assert unit["confirmation_required"] is False


def test_span_outside_every_band_is_undetectable(opts):
    doc = empty_doc(insunits=0)
    add_wall(doc, [(0, 0), (2000, 0)], width=100)  # 2000: between inch and mm bands
    with pytest.raises(ConvertError) as err:
        convert(doc_bytes(doc), opts)
    assert err.value.code == "unit_undetectable"
