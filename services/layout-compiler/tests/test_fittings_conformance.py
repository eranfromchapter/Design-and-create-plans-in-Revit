"""fixtures/pipepath/manifest.json pins the Python fittings twin (ChapterHub.Core
PipePath reads the same file): collinear merge, 90/45 elbows, unsupported bends,
zero-length and too-few-points errors; split_unsupported cuts chains at odd bends."""

from __future__ import annotations

import pytest

from layout_compiler.mep.fittings import (
    FittingError,
    classify_path,
    manifest,
    split_unsupported,
)

CASES = manifest()["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_manifest_case(case):
    if case["expect"]["ok"]:
        got = classify_path(case["path"])
        assert got.segments == case["expect"]["segments"]
        assert list(got.bends_deg) == case["expect"]["bends_deg"]
    else:
        with pytest.raises(FittingError) as err:
            classify_path(case["path"])
        assert err.value.code == case["expect"]["error"]


def test_split_unsupported_cuts_at_odd_bends_only():
    straight = [(0.0, 0.0, 2600.0), (1000.0, 0.0, 2600.0), (1000.0, 500.0, 2600.0)]
    pieces, splits = split_unsupported(straight)
    assert splits == 0 and pieces == [straight]
    skew = [
        (0.0, 0.0, 2600.0),
        (1000.0, 0.0, 2600.0),
        (1866.0254, 500.0, 2600.0),
        (1866.0254, 1500.0, 2600.0),
    ]
    pieces, splits = split_unsupported(skew)
    assert splits == 2 and len(pieces) == 3  # 30 deg then 60 deg bends: both cut
    assert pieces[0] == skew[:2] and pieces[1] == skew[1:3] and pieces[2] == skew[2:]
    for piece in pieces:
        classify_path(piece)  # every piece is a legal v1 run
