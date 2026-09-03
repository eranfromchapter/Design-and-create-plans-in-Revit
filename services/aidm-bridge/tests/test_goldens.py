"""Byte goldens (sole writer: scripts/gen_golden_render.py) and their drift: the fixture PNGs
are the sim's rasterisation of the golden views, the render response and the finish selection
re-compute to the committed bytes, and every emitted op applies in the real SimModel."""

import json

from revit_sim.model import Catalogs
from revit_sim.render.png import rasterize

from aidm_bridge.aidm import MockRenderer
from aidm_bridge.golden_render import (
    FILES,
    PHASE6_MEP_SVG,
    PX,
    VIEWS,
    compact_render,
    dumps,
    golden_render_request,
    golden_selection_request,
)
from aidm_bridge.render import RenderOptions, render_views
from aidm_bridge.selection import validate_selection

RERUN = "re-run `uv run python scripts/gen_golden_render.py` once the tolerance test passes"


def test_plan_view_is_the_phase6_golden(golden):
    assert golden["svgs"]["plan"] == PHASE6_MEP_SVG.read_text()


def test_section_and_axon_svgs_are_byte_golden(golden):
    assert golden["svgs"]["section"] == FILES["section_svg"].read_text(), RERUN
    assert golden["svgs"]["3d_hidden"] == FILES["axon_svg"].read_text(), RERUN


def test_fixture_pngs_match_the_rasterised_goldens(golden):
    for name, _ in VIEWS:
        assert rasterize(golden["svgs"][name], PX) == FILES[f"png_{name}"].read_bytes(), RERUN


def test_render_response_is_byte_golden(golden, golden_pngs):
    req = golden_render_request(golden["chain"], golden_pngs)
    resp = render_views(req, MockRenderer(), RenderOptions(req["project_id"], True))
    assert dumps(compact_render(resp)) == FILES["render_json"].read_text(), RERUN
    assert resp["prompt"]["tags_dropped"] == []


def test_finish_selection_is_byte_golden_and_applies_in_the_real_sim(golden):
    req = golden_selection_request(golden["chain"], golden["model"])
    resp = validate_selection(
        req["layout"],
        req["id_map_ids"],
        req["finish_tier"],
        req["catalog_version"],
        req["render_ref"],
        req["selection"],
        req["allow_placeholders"],
    )
    assert dumps({"request": req, "response": resp}) == FILES["selection_json"].read_text(), RERUN
    assert resp["blocking"] == [] and resp["ops"]
    committed = json.loads(FILES["selection_json"].read_text())["response"]
    assert committed["diagnostics"]["counts"]["walls_conflict"] >= 1  # the demo conflict
    model = golden["model"].clone()
    catalogs = Catalogs.load()
    for op in resp["ops"]:
        model.apply(op["op"], op["args"], catalogs)  # the executor's own law accepts them all
    assert all(
        target in model.parameters for target in {op["args"]["target_id"] for op in resp["ops"]}
    )
