"""Phase 2 acceptance: curved bay -> chained chord walls, every chord flagged
curved_approximation, per-chord true-arc sagitta <= 10 mm."""

from __future__ import annotations

import math

from scan_converter.lane_a import CONF_CHORD, convert


def _chords(result):
    return [w for w in result["layout"]["walls"] if w.get("curved_approximation")]


def test_bay_tessellates_to_seven_chained_flagged_chords(fixture_mm_bytes, opts):
    result = convert(fixture_mm_bytes, opts)
    chords = _chords(result)
    assert len(chords) == 7
    assert all(c["confidence"] == CONF_CHORD for c in chords)
    flags = {
        f["element_id"]
        for f in result["review_payload"]["flags"]
        if f["flag"] == "curved_approximation"
    }
    assert flags == {c["id"] for c in chords}

    # chained: consecutive chords share endpoints exactly; chain spans the bay
    chords.sort(key=lambda c: c["start"][0])
    assert chords[0]["start"] == [8000.0, 0.0]
    assert chords[-1]["end"] == [10000.0, 0.0]
    for a, b in zip(chords, chords[1:], strict=False):
        assert a["end"] == b["start"]

    low_ids = {w["element_id"] for w in result["review_payload"]["low_confidence"]}
    assert {c["id"] for c in chords} <= low_ids


def test_chord_sagitta_within_bound(fixture_mm_bytes, opts):
    # true arc: bulge +0.35 on chord (8000,0)->(10000,0): R=1603.57 about (9000,1253.57)
    radius = 1122500.0 / 700.0
    center = (9000.0, 2000.0 / (2 * 0.35) / 2 - 350.0 / 2)  # = (9000, 1253.571...)
    center = (9000.0, radius - 350.0)
    result = convert(fixture_mm_bytes, opts)
    for chord in _chords(result):
        mid = (
            (chord["start"][0] + chord["end"][0]) / 2,
            (chord["start"][1] + chord["end"][1]) / 2,
        )
        sagitta = radius - math.hypot(mid[0] - center[0], mid[1] - center[1])
        assert 0.0 <= sagitta <= 10.0 + 0.05  # emit rounding tolerance
