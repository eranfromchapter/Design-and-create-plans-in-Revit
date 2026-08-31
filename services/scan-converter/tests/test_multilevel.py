"""Phase 2 acceptance: multi-level bundles rejected with a clear message — both
detection signals (elevation clusters, storey-pattern layer names). Never
silently flattened (PLAN.md D1)."""

from __future__ import annotations

import pytest
from helpers import add_wall, doc_bytes, empty_doc

from scan_converter.lane_a import ConvertError, convert


def test_two_elevation_clusters_rejected(opts):
    doc = empty_doc()
    add_wall(doc, [(0, 0), (8000, 0)], width=200)
    second = doc.modelspace().add_lwpolyline(
        [(0, 3000, 0.0), (8000, 3000, 0.0)],
        format="xyb",
        dxfattribs={"layer": "WALLS", "const_width": 200},
    )
    second.dxf.elevation = 2700.0  # a second storey drawn 2.7 m up
    with pytest.raises(ConvertError) as err:
        convert(doc_bytes(doc), opts)
    assert err.value.code == "multi_level_unsupported"
    assert "elevation" in err.value.message


def test_storey_layer_name_rejected(opts):
    doc = empty_doc()
    doc.layers.add("FLOOR_2")
    add_wall(doc, [(0, 0), (8000, 0)], width=200)
    add_wall(doc, [(0, 3000), (8000, 3000)], width=200, layer="FLOOR_2")
    with pytest.raises(ConvertError) as err:
        convert(doc_bytes(doc), opts)
    assert err.value.code == "multi_level_unsupported"
    assert "FLOOR_2" in err.value.message


def test_single_level_with_benign_layer_names_passes(opts):
    doc = empty_doc()
    doc.layers.add("FLOOR_FINISH")  # matches the words but not the storey pattern
    add_wall(doc, [(0, 0), (8000, 0)], width=200)
    doc.modelspace().add_text("OAK", dxfattribs={"layer": "FLOOR_FINISH", "insert": (10, 10)})
    assert convert(doc_bytes(doc), opts)["layout"]["walls"]
