"""Phase 2 acceptance: near-orthogonal walls snap EXACTLY to the dominant axis;
genuine skews are preserved, flagged, and confidence-priced."""

from __future__ import annotations

from helpers import add_wall, doc_bytes, empty_doc

from scan_converter.lane_a import CONF_SKEW, convert


def _walls_by_id(result):
    return {w["id"]: w for w in result["layout"]["walls"]}


def test_fixture_divider_snaps_exactly_horizontal(fixture_mm_bytes, opts):
    result = convert(fixture_mm_bytes, opts)
    # the divider was drawn (0,3800)->(3600,3850): 0.796 deg off, inside the
    # 1.5 deg tolerance -> must land exactly horizontal at the projected midline
    divider = next(
        w
        for w in result["layout"]["walls"]
        if w["as_built_thickness"] == 100.0 and w["start"][1] in (3825.0,)
    )
    assert divider["start"] == [0.0, 3825.0]
    assert divider["end"] == [3600.0, 3825.0]
    assert divider["start"][1] == divider["end"][1]
    skew_flags = [f for f in result["review_payload"]["flags"] if f["flag"] == "skewed"]
    assert all(f["element_id"] != divider["id"] for f in skew_flags)


def test_fixture_orthogonal_walls_land_exactly(fixture_mm_bytes, opts):
    result = convert(fixture_mm_bytes, opts)
    walls = _walls_by_id(result)
    # W party wall and N corridor wall drawn exactly orthogonal: coordinates
    # survive conversion byte-exactly
    assert walls["W-001"]["start"] == [0.0, 0.0] and walls["W-001"]["end"] == [0.0, 7000.0]
    assert walls["W-004"]["start"] == [0.0, 7000.0]
    assert walls["W-004"]["end"] == [11400.0, 7000.0]


def test_fixture_foyer_wall_preserved_and_flagged(fixture_mm_bytes, opts):
    result = convert(fixture_mm_bytes, opts)
    walls = _walls_by_id(result)
    foyer = walls["W-008"]  # (7000,4600)->(7150,7000), 3.58 deg off vertical
    assert foyer["start"] == [7000.0, 4600.0]
    assert foyer["end"] == [7150.0, 7000.0]
    assert foyer["confidence"] == CONF_SKEW
    flags = result["review_payload"]["flags"]
    assert any(f["element_id"] == "W-008" and f["flag"] == "skewed" for f in flags)
    assert any(w["element_id"] == "W-008" for w in result["review_payload"]["low_confidence"])


def test_isolated_skew_beyond_tolerance_never_snaps(opts):
    doc = empty_doc()
    # enough orthogonal fabric that the skew cannot win the dominant axis
    add_wall(doc, [(0, 0), (8000, 0)], width=200)
    add_wall(doc, [(0, 6000), (8000, 6000)], width=200)
    add_wall(doc, [(0, 0), (0, 6000)], width=200)
    add_wall(doc, [(0, 3000), (8000, 3400)], width=100)  # 2.86 deg off
    result = convert(doc_bytes(doc), opts)
    skewed = next(w for w in result["layout"]["walls"] if w["as_built_thickness"] == 100.0)
    assert skewed["end"] == [8000.0, 3400.0]  # untouched
    assert skewed["confidence"] == CONF_SKEW
