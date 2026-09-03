"""Phase 7 section renderer (docs/PHASE7_DESIGN.md P7-11): an elevation through the bbox
centre looking +Y, canonical by construction like render_plan."""

import re
import xml.etree.ElementTree as ET

from phase7_helpers import CATALOGS, build_room

from revit_sim.render.svg import render_plan, render_section


def _rect(svg: str, element_id: str, cls: str) -> dict[str, float] | None:
    m = re.search(
        rf'<rect class="{cls}" data-id="{element_id}" x="([-\d.]+)" y="([-\d.]+)" '
        rf'width="([-\d.]+)" height="([-\d.]+)"',
        svg,
    )
    if m is None:
        return None
    x, y, w, h = (float(v) for v in m.groups())
    return {"x": x, "y": y, "w": w, "h": h}


def test_section_bytes_independent_of_insertion_order():
    a = render_section(build_room((1, 2, 3, 4), family_order=(1, 2)), CATALOGS)
    b = render_section(build_room((4, 2, 1, 3), family_order=(2, 1)), CATALOGS)
    assert a == b


def test_section_rerender_identical_and_plan_untouched():
    model = build_room()
    assert render_section(model, CATALOGS) == render_section(model, CATALOGS)
    # the plan renderer is untouched by the Phase 7 additions (goldens 1-6 stay byte-stable)
    assert render_plan(model) == render_plan(model)
    assert "wall standing" in render_plan(model)


def test_section_classifies_walls_against_the_cut():
    svg = render_section(build_room(), CATALOGS)
    assert _rect(svg, "W-003", "wall elevation") is not None  # at/beyond the cut
    assert _rect(svg, "W-002", "wall cut") is not None
    assert _rect(svg, "W-004", "wall cut") is not None
    assert 'data-id="W-001"' not in svg  # behind the cut: omitted


def test_section_one_opening_per_door_on_elevation_walls():
    svg = render_section(build_room(), CATALOGS)
    door = _rect(svg, "D-001", "opening door")
    assert door is not None
    assert door["y"] == -2032.0 and door["h"] == 2032.0 and door["w"] == 813.0
    window = _rect(svg, "N-001", "opening window")
    assert window is not None
    assert window["y"] == -(900.0 + 1400.0) and window["h"] == 1400.0
    assert 'data-id="D-002"' not in svg  # hosted by the wall behind the cut
    assert svg.count('class="opening door"') == 1


def test_section_cut_wall_shows_the_opening_the_cut_passes_through():
    svg = render_section(build_room(), CATALOGS)
    cut = _rect(svg, "W-002", "wall cut")
    opening = _rect(svg, "D-003", "opening door cut")
    assert cut is not None and opening is not None
    assert opening["x"] == cut["x"] and opening["w"] == cut["w"]
    assert opening["y"] == -2032.0


def test_section_family_height_from_clash_prisms_and_behind_omitted():
    svg = render_section(build_room(), CATALOGS)
    bed = _rect(svg, "F-001", "family")
    assert bed is not None and bed["h"] == 600.0 and bed["y"] == -600.0  # kind_heights_mm.bed
    assert 'data-id="F-002"' not in svg  # the wc sits entirely behind the cut


def test_section_device_pipe_conduit_and_viewbox():
    svg = render_section(build_room(), CATALOGS)
    assert 'class="device receptacle" data-id="E-001"' in svg
    assert 'class="pipe sanitary" data-id="P-001" points="500.0,300.0 3500.0,300.0"' in svg
    assert 'class="conduit" data-id="Q-001" points="500.0,-2600.0 3500.0,-2600.0"' in svg
    view_box = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg)
    assert view_box is not None
    x, y, w, h = (float(v) for v in view_box.groups())
    assert y + h >= 300.0 + 250.0  # the under-slab pipe extends the viewBox downwards
    assert y <= -(2700.0 + 250.0)
    assert x == -250.0 and w == 4500.0


def test_section_is_parseable_xml():
    root = ET.fromstring(render_section(build_room(), CATALOGS))
    assert root.tag.endswith("svg")
    assert len(list(root)) > 5
