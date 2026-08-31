"""Phase 2 acceptance: everything below confidence 0.85 appears in the review
payload; the height assumption is a first-class review field; profile
violations and empty documents reject with diagnostics."""

from __future__ import annotations

import pytest
from helpers import add_line, add_wall, doc_bytes, empty_doc

from scan_converter.lane_a import LOW_CONFIDENCE_THRESHOLD, ConvertError, convert


def test_low_confidence_list_is_exactly_the_sub_085_set(fixture_mm_bytes, opts):
    result = convert(fixture_mm_bytes, opts)
    layout = result["layout"]
    expected = {
        rec["id"]
        for group in ("walls", "doors", "windows")
        for rec in layout[group]
        if rec["confidence"] < LOW_CONFIDENCE_THRESHOLD
    }
    listed = {e["element_id"] for e in result["review_payload"]["low_confidence"]}
    assert listed == expected
    # the fixture pins the census: 7 chords + 1 skew + 5 doors + 3 windows
    assert len(result["review_payload"]["low_confidence"]) == 16


def test_ordinary_walls_stay_off_the_review_list(fixture_mm_bytes, opts):
    result = convert(fixture_mm_bytes, opts)
    listed = {e["element_id"] for e in result["review_payload"]["low_confidence"]}
    # snapped orthogonal, in-bucket walls sit at exactly 0.85 and are NOT listed
    assert "W-001" not in listed and "W-004" not in listed


def test_height_assumption_is_first_class(fixture_mm_bytes, opts):
    review = convert(fixture_mm_bytes, opts)["review_payload"]
    assert review["height_assumption_mm"] == 2700.0
    assert any(a["field"] == "wall_height" for a in review["assumptions"])
    # heights are applied to every wall pending confirmation
    assert all(w["height"] == 2700.0 for w in review["layout"]["walls"])


def test_counts_and_room_labels(fixture_mm_bytes, opts):
    review = convert(fixture_mm_bytes, opts)["review_payload"]
    assert review["counts"] == {"walls": 17, "doors": 5, "windows": 3}
    assert {label["text"] for label in review["room_labels"]} == {
        "BEDROOM 1",
        "BEDROOM 2",
        "BATH",
        "KITCHEN",
        "LIVING ROOM",
        "FOYER",
    }


def test_zero_width_walls_are_profile_violations(opts):
    doc = empty_doc()
    add_wall(doc, [(0, 0), (8000, 0)], width=0)
    with pytest.raises(ConvertError) as err:
        convert(doc_bytes(doc), opts)
    assert err.value.code == "profile_violation"
    assert "const_width" in err.value.message


def test_lines_on_wall_layer_are_profile_violations(opts):
    doc = empty_doc()
    add_line(doc, (0, 0), (8000, 0), "WALLS")
    with pytest.raises(ConvertError) as err:
        convert(doc_bytes(doc), opts)
    assert err.value.code == "profile_violation"


def test_empty_document_rejects_with_layer_census(opts):
    doc = empty_doc()
    doc.modelspace().add_text("HELLO", dxfattribs={"layer": "ROOMS", "insert": (0, 0)})
    with pytest.raises(ConvertError) as err:
        convert(doc_bytes(doc), opts)
    assert err.value.code == "no_walls_found"
    assert "ROOMS(1)" in err.value.message


def test_garbage_bytes_reject_as_parse_error(opts):
    with pytest.raises(ConvertError) as err:
        convert(b"\x00\x01this is not a dxf", opts)
    assert err.value.code == "dxf_parse_error"
