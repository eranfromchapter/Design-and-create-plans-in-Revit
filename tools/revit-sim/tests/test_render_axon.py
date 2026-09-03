"""Phase 7 axonometric renderer (docs/PHASE7_DESIGN.md P7-11, deviation D-3): wall slabs and
family footprints as painter-ordered boxes with viewer-facing faces only."""

import re

from phase7_helpers import BED, CATALOGS, build_room, family_args

from revit_sim.model import SimModel
from revit_sim.render.svg import render_axon


def _boxes(svg: str) -> list[str]:
    return re.findall(r'<g class="box (?:wall|family)" data-id="([A-Z]-\d{3})">', svg)


def _polygons_of(svg: str, element_id: str) -> int:
    m = re.search(rf'<g class="box (?:wall|family)" data-id="{element_id}">(.*?)</g>', svg)
    assert m is not None
    return m.group(1).count("<polygon ")


def test_axon_box_count_equals_walls_plus_families():
    model = build_room()
    svg = render_axon(model, CATALOGS)
    assert len(_boxes(svg)) == len(model.walls) + len(model.families)


def test_axon_insertion_order_invariance_and_rerender_identity():
    a = render_axon(build_room((1, 2, 3, 4), family_order=(1, 2)), CATALOGS)
    b = render_axon(build_room((4, 2, 1, 3), family_order=(2, 1)), CATALOGS)
    assert a == b
    assert a == render_axon(build_room(), CATALOGS)


def test_axon_axis_aligned_box_shows_two_sides_and_the_top():
    svg = render_axon(build_room(with_mep=False), CATALOGS)
    for element_id in ("W-001", "W-002", "W-003", "W-004", "F-001", "F-002"):
        assert _polygons_of(svg, element_id) == 3


def test_axon_rotated_family_selects_faces_by_normal():
    model = SimModel()
    model.apply("place_family", family_args(1, BED[0], BED[1], [0, 0], BED[2], 45.0), CATALOGS)
    model.apply("place_family", family_args(2, BED[0], BED[1], [5000, 0], BED[2], 30.0), CATALOGS)
    svg = render_axon(model, CATALOGS)
    assert _polygons_of(svg, "F-001") == 2  # two faces exactly edge-on at 45 deg: omitted
    assert _polygons_of(svg, "F-002") == 3


def test_axon_painters_order_far_first():
    model = build_room(with_mep=False)
    svg = render_axon(model, CATALOGS)
    order = _boxes(svg)

    def key(element_id: str) -> float:  # centroid x+y per box; far (larger) first
        if element_id in model.walls:
            w = model.walls[element_id]
            return -(w["start"][0] + w["end"][0] + w["start"][1] + w["end"][1]) / 2
        cx, cy = model.families[element_id]["center"]
        return -(cx + cy)

    assert order == sorted(order, key=lambda i: (key(i), i))
    assert order[0] == "W-002"  # the wall at x = 4000 is the farthest box
