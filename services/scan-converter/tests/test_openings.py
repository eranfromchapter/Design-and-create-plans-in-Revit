"""Opening mapping: host resolution, centerline offsets, defaults, and the
out-of-contract exclusions (flagged, never silently dropped)."""

from __future__ import annotations

from helpers import add_line, add_wall, doc_bytes, empty_doc

from scan_converter.lane_a import convert


def test_fixture_openings_map_to_expected_hosts(fixture_mm_bytes, opts):
    result = convert(fixture_mm_bytes, opts)
    doors = {d["id"]: d for d in result["layout"]["doors"]}
    windows = {n["id"]: n for n in result["layout"]["windows"]}
    assert len(doors) == 5 and len(windows) == 3

    # entry door on the N corridor wall (W-004), centered at x=8600
    assert doors["D-001"]["host_wall_id"] == "W-004"
    assert doors["D-001"]["offset"] == 8600.0
    assert doors["D-001"]["width"] == 915.0
    # bedroom doors on the spine (W-005), sorted by offset
    assert doors["D-002"]["host_wall_id"] == "W-005"
    assert doors["D-002"]["offset"] == 2000.0 and doors["D-002"]["width"] == 762.0
    assert doors["D-003"]["host_wall_id"] == "W-005"
    assert doors["D-003"]["offset"] == 4212.0 and doors["D-003"]["width"] == 711.0
    # bath + kitchen doors on the wet-block wall (W-006)
    assert doors["D-004"]["host_wall_id"] == "W-006" and doors["D-004"]["offset"] == 850.0
    assert doors["D-005"]["host_wall_id"] == "W-006" and doors["D-005"]["offset"] == 2550.0

    # facade windows: two on the west straight (W-002), one east of the bay (W-016)
    assert windows["N-001"]["host_wall_id"] == "W-002" and windows["N-001"]["offset"] == 1800.0
    assert windows["N-002"]["host_wall_id"] == "W-002" and windows["N-002"]["offset"] == 6800.0
    assert windows["N-003"]["host_wall_id"] == "W-016" and windows["N-003"]["offset"] == 700.0
    assert windows["N-003"]["width"] == 915.0

    # 2D assumptions applied and priced into confidence
    for d in doors.values():
        assert d["height"] == 2040.0 and d["swing"] == "L" and d["confidence"] == 0.8
    for n in windows.values():
        assert n["sill_height"] == 900.0 and n["height"] == 1400.0


def test_opening_far_from_any_wall_is_flagged_not_dropped(opts):
    doc = empty_doc()
    add_wall(doc, [(0, 0), (8000, 0)], width=200)
    add_line(doc, (2000, 900), (2915, 900), "DOORS")  # 900mm off the wall
    result = convert(doc_bytes(doc), opts)
    assert result["layout"]["doors"] == []
    assert any(f["flag"] == "unmapped_opening" for f in result["review_payload"]["flags"])


def test_door_width_outside_contract_bounds_is_excluded(opts):
    doc = empty_doc()
    add_wall(doc, [(0, 0), (8000, 0)], width=200)
    add_line(doc, (1000, 0), (1500, 0), "DOORS")  # 500mm < 610 contract minimum
    result = convert(doc_bytes(doc), opts)
    assert result["layout"]["doors"] == []
    flags = result["review_payload"]["flags"]
    assert any(f["flag"] == "unmapped_opening" and "bounds" in f["detail"] for f in flags)


def test_opening_overrunning_host_end_is_excluded(opts):
    doc = empty_doc()
    add_wall(doc, [(0, 0), (2000, 0)], width=300)
    # 915 wide centered at offset 1700: spans to x=2157.5, overrunning the wall end
    # while both endpoints stay inside the t/2+50 host slack (200)
    add_line(doc, (1242.5, 0), (2157.5, 0), "DOORS")
    result = convert(doc_bytes(doc), opts)
    assert result["layout"]["doors"] == []
    assert any(
        f["flag"] == "unmapped_opening" and "overruns" in f["detail"]
        for f in result["review_payload"]["flags"]
    )
