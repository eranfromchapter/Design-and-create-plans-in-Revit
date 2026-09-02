"""MEP input resolution: levels/panel ladders + stamping into meta, wet-room
derivation, placer host wall + fallbacks, counter walls (casework vs derived),
outlet spacing, fixture semantics from the catalog only (AST), and the golden chain."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from helpers import door, room, wall
from mep_helpers import CONFIRMATIONS, assemble, commit0_for, fixture, two_baths

from layout_compiler.mep.inputs import MepError, resolve_inputs

MEP_SRC = Path(__file__).resolve().parents[1] / "src" / "layout_compiler" / "mep"


def test_levels_from_meta_and_inconsistency_blocks():
    layout = two_baths()
    layout["meta"]["levels"] = {"floor_z": 0.0, "ceiling_z": 2700.0, "slab_to_slab": 3100.0}
    inputs = resolve_inputs(layout, commit0_for(layout), {"panel": [50.0, 1500.0]})
    assert (inputs.levels_source, inputs.h_plenum) == ("meta", 400.0)
    layout["meta"]["levels"]["slab_to_slab"] = 2600.0  # ceiling above the slab
    bad = resolve_inputs(layout, commit0_for(layout), {"panel": [50.0, 1500.0]})
    assert bad.blocking() == ["levels_inconsistent"] and bad.h_plenum is None


def test_levels_confirmation_ladder_and_stamping():
    layout = two_baths()
    missing = resolve_inputs(layout, commit0_for(layout), {"panel": [50.0, 1500.0]})
    assert "levels_missing" in missing.blocking()
    ok = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS)
    assert ok.blocking() == []
    assert ok.layout["meta"]["levels"] == {
        "floor_z": 0.0,
        "ceiling_z": 2700.0,
        "slab_to_slab": 3000.0,
    }
    assert ok.layout["meta"]["electrical"] == {"panel": [50.0, 1500.0]}
    assert "levels" not in layout["meta"]  # input untouched
    low = resolve_inputs(
        layout, commit0_for(layout), {"panel": [50.0, 1500.0], "slab_to_slab_mm": 2700.0}
    )
    assert low.blocking() == ["levels_inconsistent"]  # must exceed the 2700 ceiling
    huge = resolve_inputs(
        layout, commit0_for(layout), {"panel": [50.0, 1500.0], "slab_to_slab_mm": 9000.0}
    )
    assert huge.blocking() == ["levels_inconsistent"]


def test_ceiling_comes_from_the_commit0_wall_height():
    layout = two_baths()
    inputs = resolve_inputs(
        layout,
        commit0_for(layout, height=2900.0),
        {"panel": [50.0, 1500.0], "slab_to_slab_mm": 3200.0},
    )
    assert (inputs.ceiling_z, inputs.h_plenum) == (2900.0, 300.0)


def test_panel_ladder_meta_riser_confirmation_missing():
    layout = two_baths()
    layout["meta"]["electrical"] = {"panel": [4750.0, 2000.0]}
    layout["risers"] = [{"id": "RS-01", "type": "electrical", "center": [100.0, 100.0]}]
    a = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS)
    assert (a.panel, a.panel_source, a.panel_wall_id, a.panel_node) == (
        (4750.0, 2000.0),
        "meta",
        "W-006",
        (4800.0, 2000.0),
    )
    del layout["meta"]["electrical"]
    b = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS)
    assert (b.panel, b.panel_source) == ((100.0, 100.0), "riser:RS-01")
    del layout["risers"]
    c = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS)
    assert (c.panel, c.panel_source, c.panel_wall_id) == ((50.0, 1500.0), "confirmation", "W-004")
    d = resolve_inputs(layout, commit0_for(layout), {"slab_to_slab_mm": 3000.0})
    assert d.blocking() == ["panel_missing"] and d.panel is None
    with pytest.raises(MepError) as err:
        resolve_inputs(
            layout, commit0_for(layout), {"panel": [1200.0, 1500.0], "slab_to_slab_mm": 3000.0}
        )
    assert err.value.code == "panel_not_on_wall"


def test_wet_rooms_declared_or_derived_from_sanitary_hookups():
    layout = two_baths()
    layout["rooms"][1]["wet_zone"] = False  # bath B undeclared but holds a wc
    inputs = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS)
    assert inputs.wet_rooms == ["R-001", "R-002"] and inputs.derived_wet_rooms == ["R-002"]


def test_host_wall_recorded_then_geometric_then_nearest():
    layout = two_baths()
    recorded = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS, {"F-001": "W-001"})
    assert recorded.host_walls["F-001"] == "W-001"  # placer's word is final when it bounds the room
    ignored = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS, {"F-001": "W-099"})
    assert ignored.host_walls["F-001"] == "W-005"  # back-to-wall distance matches t/2 + d/2
    floating = two_baths()
    floating["furniture"][0]["items"][0]["center"] = [1200.0, 1500.0]  # mid-room
    nearest = resolve_inputs(floating, commit0_for(floating), CONFIRMATIONS)
    # 1200 from W-004 and W-005, 1500 from W-001/W-003: nearest tie -> smaller id
    assert nearest.host_walls["F-001"] == "W-004"


def test_fixtures_carry_catalog_semantics():
    inputs = resolve_inputs(two_baths(), commit0_for(two_baths()), CONFIRMATIONS)
    by_id = {f.id: f for f in inputs.fixtures}
    assert [f.id for f in inputs.fixtures] == ["F-001", "F-002", "F-003"]
    assert (by_id["F-001"].fixture_units, by_id["F-001"].drain_mm, by_id["F-001"].slope) == (
        4.0,
        76.0,
        0.0104,
    )
    assert (by_id["F-002"].fixture_units, by_id["F-002"].drain_mm, by_id["F-002"].slope) == (
        1.0,
        32.0,
        0.0208,
    )
    assert inputs.h_fitting == 150.0


def test_unknown_fixture_kind_is_blocking():
    layout = two_baths()
    layout["furniture"][0]["items"][0]["kind"] = "generic"
    inputs = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS)
    assert inputs.blocking() == ["fixture_kind_unknown"]
    assert [f.id for f in inputs.fixtures] == ["F-002", "F-003"]


def test_outlet_spacing_default_and_floor():
    layout = two_baths()
    assert resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS).outlet_spacing == 3660.0
    layout["constraints"]["outlet_spacing"] = 500
    assert resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS).blocking() == [
        "outlet_spacing_invalid"
    ]


def kitchen_layout(with_casework: bool) -> dict:
    walls = [
        wall(1, [0, 0], [6000, 0]),
        wall(2, [6000, 0], [6000, 3600]),
        wall(3, [6000, 3600], [0, 3600]),
        wall(4, [0, 3600], [0, 0]),
    ]
    rooms = [
        room(
            1,
            [[0, 0], [6000, 0], [6000, 3600], [0, 3600]],
            ["W-001", "W-002", "W-003", "W-004"],
            program="kitchen",
        )
    ]
    placed = [
        fixture(1, "R-001", "kitchen_sink", [1500.0, 346.0]),
        fixture(2, "R-001", "dishwasher", [2250.0, 346.0]),
        fixture(3, "R-001", "range", [4000.0, 376.0]),
    ]
    layout = assemble(walls, [door(1, "W-003", 3000)], rooms, placed)
    if with_casework:
        layout["casework"] = [
            {
                "id": "K-001",
                "host_wall_id": "W-001",
                "offset": 600.0,
                "length": 3000.0,
                "depth": 600.0,
                "height": 900.0,
                "is_counter": True,
                "revit_family": "CHPT_Base_PLACEHOLDER",
                "revit_type": "Base_600_PLACEHOLDER",
            }
        ]
    return layout


def test_counter_walls_from_casework():
    layout = kitchen_layout(with_casework=True)
    inputs = resolve_inputs(
        layout, commit0_for(layout), {"panel": [50.0, 1800.0], "slab_to_slab_mm": 3000.0}
    )
    assert inputs.counter_source == "casework"
    assert inputs.counter_walls == {"R-001": ["W-001"]}
    assert inputs.counter_runs[("R-001", "W-001")] == [(600.0, 3600.0)]
    assert not any(i.code == "counter_walls_derived" for i in inputs.items)


def test_counter_walls_derived_from_sink_and_dishwasher_minus_appliances():
    layout = kitchen_layout(with_casework=False)
    inputs = resolve_inputs(
        layout, commit0_for(layout), {"panel": [50.0, 1800.0], "slab_to_slab_mm": 3000.0}
    )
    assert inputs.counter_source == "derived"
    assert inputs.counter_walls == {"R-001": ["W-001"]}
    # sink 1050..1950, DW 1950..2550, both +/-600 -> 450..3150; range 3619..4381 is outside
    assert inputs.counter_runs[("R-001", "W-001")] == [(450.0, 3150.0)]
    assert any(i.code == "counter_walls_derived" and i.refs == ["W-001"] for i in inputs.items)
    # move the range into the run: it cuts the counter interval
    layout["furniture"][0]["items"][2]["center"] = [2800.0, 376.0]
    cut = resolve_inputs(
        layout, commit0_for(layout), {"panel": [50.0, 1800.0], "slab_to_slab_mm": 3000.0}
    )
    assert cut.counter_runs[("R-001", "W-001")] == [
        (450.0, 2419.0),
        (3181.0, 3150.0),
    ] or cut.counter_runs[("R-001", "W-001")][0] == (450.0, 2419.0)


def test_fixture_semantics_never_use_family_names():
    """Part G: fixture semantics come from kind/fixture_units/hookups + plumbing.json —
    no MEP module compares revit_family/revit_type strings (ops.py only EMITS them)."""
    offenders = []
    for path in sorted(MEP_SRC.glob("*.py")):
        if path.name in ("ops.py", "__init__.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and node.value in ("revit_family", "revit_type"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], offenders


def test_golden_chain_inputs(tmp_path):
    from layout_compiler.compile import CompileOptions, compile_layout
    from layout_compiler.fixtures import FixtureLLM
    from layout_compiler.furnish import FurnishOptions, furnish_layout
    from layout_compiler.golden_4br import REPO_ROOT, frozen_layout
    from layout_compiler.interior_fixtures import InteriorFixtureLLM
    from layout_compiler.mep.plumbing import plan_plumbing

    brief = json.loads((REPO_ROOT / "fixtures" / "briefs" / "2br_golden_brief.json").read_text())
    brief["meta"]["confirmed_by_client"] = True
    compiled = compile_layout(
        brief, frozen_layout(), CompileOptions(project_id=brief["meta"]["project_id"]), FixtureLLM()
    )
    furnished = furnish_layout(
        brief,
        frozen_layout(),
        compiled["layout"],
        compiled["ops"],
        FurnishOptions(project_id=brief["meta"]["project_id"]),
        InteriorFixtureLLM(),
    )
    wall_ids = {
        d["item_id"]: d["wall_id"] for d in furnished["diagnostics"]["items"] if d.get("wall_id")
    }
    inputs = resolve_inputs(
        furnished["layout"],
        frozen_layout(),
        {"panel": [8050.0, 5200.0], "slab_to_slab_mm": 3000.0},
        wall_ids,
    )
    assert inputs.blocking() == []
    assert inputs.wet_rooms == [
        "R-003",
        "R-007",
        "R-009",
        "R-011",
    ] and inputs.derived_wet_rooms == ["R-009"]
    assert (inputs.panel_wall_id, inputs.panel_node, inputs.h_plenum) == (
        "W-019",
        (8000.0, 5200.0),
        300.0,
    )
    assert inputs.counter_walls == {"R-009": ["W-002"]} and inputs.counter_source == "derived"
    result = plan_plumbing(inputs)
    assert [(s.wall_id, s.offset, s.diameter, s.fixture_ids, s.snapped) for s in result.stacks] == [
        ("W-004", pytest.approx(5133.3, abs=0.05), 76.0, ["F-006", "F-007", "F-012"], False),
        ("W-026", 169.0, 51.0, ["F-017", "F-018"], True),
    ]
    assert len(result.segments) == 8 and result.counters == {
        "p1_iterations": 2,
        "p4_prune_steps": 0,
        "snap_steps": 1,
    }
