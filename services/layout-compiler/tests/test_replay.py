"""Sim-replay conformance: the review card renders through the sim's canonical
renderer, byte-identical to post-commit reality — fixtures/goldens/phase2_2br.svg
pins the Commit #0 replay — and demolished elements render dashed. Also the
preflight negative: an op the sim would reject fails here."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from revit_sim.model import OpError
from revit_sim.render.svg import render_plan

from layout_compiler.replay import render_review_svgs, sim_model_from_layout

REPO = Path(__file__).resolve().parents[3]
GOLDEN_LAYOUT = json.loads((REPO / "fixtures" / "layouts" / "2br_golden.json").read_text())
GOLDEN_SVG = (REPO / "fixtures" / "goldens" / "phase2_2br.svg").read_text()


def svg_line(svg: str, element_id: str) -> str:
    lines = [line for line in svg.splitlines() if f'data-id="{element_id}"' in line]
    assert len(lines) == 1
    return lines[0]


def test_commit0_replay_matches_phase2_golden_bytes():
    assert render_plan(sim_model_from_layout(GOLDEN_LAYOUT)) == GOLDEN_SVG


def test_demolished_elements_render_dashed_only_in_new_svg():
    ops = [
        {"op": "set_phase_demolished", "args": {"target_id": "D-002"}},
        {"op": "set_phase_demolished", "args": {"target_id": "W-007"}},
    ]
    svgs = render_review_svgs(GOLDEN_LAYOUT, ops)
    assert svgs["existing"] == GOLDEN_SVG
    assert "stroke-dasharray" not in svgs["existing"]
    wall = svg_line(svgs["new"], "W-007")
    assert 'class="wall demolished"' in wall and "stroke-dasharray" in wall
    door = svg_line(svgs["new"], "D-002")
    assert 'class="door demolished"' in door and "stroke-dasharray" in door
    standing = svg_line(svgs["new"], "W-006")
    assert 'class="wall standing"' in standing and "stroke-dasharray" not in standing


def test_unknown_revit_type_rejected_by_sim_preflight():
    op = {
        "op": "create_wall",
        "args": {
            "id": "W-999",
            "start": [0, 0],
            "end": [1000, 0],
            "revit_type": "NOT_A_CATALOG_TYPE",
            "height": 2700,
            "phase": "new",
        },
    }
    with pytest.raises(OpError) as err:
        render_review_svgs(GOLDEN_LAYOUT, [op])
    assert err.value.code == "unknown_revit_type"
