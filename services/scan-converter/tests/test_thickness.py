"""Phase 2 acceptance: thickness classification into ±10 mm catalog buckets;
out-of-bucket -> nearest type + flag + confidence 0.55."""

from __future__ import annotations

from helpers import add_wall, doc_bytes, empty_doc

from scan_converter.lane_a import CONF_THICKNESS_MISMATCH, convert


def _single_wall(opts, thickness: float):
    doc = empty_doc()
    add_wall(doc, [(0, 0), (8000, 0)], width=thickness)
    result = convert(doc_bytes(doc), opts)
    return result["layout"]["walls"][0], result["review_payload"]


def test_exact_bucket(opts):
    wall, _ = _single_wall(opts, 200.0)
    assert wall["revit_type"] == "CHPT_AsBuilt_200mm_PLACEHOLDER"
    assert wall["as_built_thickness"] == 200.0
    assert wall["confidence"] == 0.85  # ortho 0.95 capped at CAP_2D


def test_boundary_inside_bucket(opts):
    wall, review = _single_wall(opts, 210.0)  # exactly +10: inside
    assert wall["revit_type"] == "CHPT_AsBuilt_200mm_PLACEHOLDER"
    assert all(f["flag"] != "thickness_out_of_bucket" for f in review["flags"])


def test_just_outside_bucket_flags_nearest(opts):
    wall, review = _single_wall(opts, 210.1)
    assert wall["revit_type"] == "CHPT_AsBuilt_200mm_PLACEHOLDER"  # nearest
    assert wall["confidence"] == CONF_THICKNESS_MISMATCH
    assert any(f["flag"] == "thickness_out_of_bucket" for f in review["flags"])
    assert any(w["element_id"] == wall["id"] for w in review["low_confidence"])


def test_midpoint_between_buckets_prefers_thinner(opts):
    wall, _ = _single_wall(opts, 125.0)  # equidistant 100/150 -> deterministic: 100
    assert wall["revit_type"] == "CHPT_AsBuilt_100mm_PLACEHOLDER"
