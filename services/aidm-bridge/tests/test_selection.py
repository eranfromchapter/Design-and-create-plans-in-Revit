"""Finish-selection validator semantics (docs/PHASE7_DESIGN.md P7-08, P7-14) incl. the PLAN
Phase 7 acceptance negative: the emitted set_parameter ops use only allowlisted params."""

import copy
import json

import pytest
from helpers import GOLDEN_LAYOUT, layout_ids

from aidm_bridge import selection as sel
from aidm_bridge.catalogs import catalog_version, param_allowlist
from aidm_bridge.selection import (
    PARAM_COMMENTS,
    PARAM_MATERIAL,
    PARAM_RENDER_REF,
    PARAM_SKU,
    PARAM_SPEC,
    SelectionError,
    validate_ops,
    validate_selection,
)

STD_PAINT = "CHPT-WALL-PAINT-STD_PLACEHOLDER"
LUX_TILE = "CHPT-WALL-TILE-LUX_PLACEHOLDER"
STD_DOOR = "CHPT-DOOR-SC-STD_PLACEHOLDER"
STD_WC = "CHPT-WC-STD_PLACEHOLDER"
STD_LAV = "CHPT-LAV-STD_PLACEHOLDER"
DW = "CHPT-APPL-DW-STD_PLACEHOLDER"
IDS = layout_ids(GOLDEN_LAYOUT)
ROOMS = {r["id"]: r for r in GOLDEN_LAYOUT["rooms"]}
ITEMS = {i["id"]: i for g in GOLDEN_LAYOUT["furniture"] for i in g["items"]}
WC_IDS = sorted(i for i, it in ITEMS.items() if it["kind"] == "wc")
LAV_IDS = sorted(i for i, it in ITEMS.items() if it["kind"] == "lav")
DW_IDS = sorted(i for i, it in ITEMS.items() if it["kind"] == "dishwasher")
BED_IDS = sorted(i for i, it in ITEMS.items() if it["kind"] == "bed")


def run(selection, *, ids=IDS, tier="standard", render_ref="mock-ref", allow=True, layout=None):
    return validate_selection(
        layout or GOLDEN_LAYOUT, ids, tier, catalog_version(), render_ref, selection, allow
    )


def empty(**parts):
    base = {"rooms": [], "casework": [], "doors": [], "plumbing_fixtures": [], "overrides": []}
    base.update(parts)
    return base


def test_single_room_wall_finish_emits_four_params_per_wall_sorted():
    room = "R-001"
    out = run(empty(rooms=[{"room_id": room, "wall_sku": STD_PAINT}]))
    assert out["blocking"] == []
    walls = ROOMS[room]["boundary_wall_ids"]
    assert {op["args"]["target_id"] for op in out["ops"]} == set(walls)
    per_wall = {}
    for op in out["ops"]:
        per_wall.setdefault(op["args"]["target_id"], []).append(op["args"]["param"])
    for params in per_wall.values():
        assert params == sorted([PARAM_MATERIAL, PARAM_SKU, PARAM_RENDER_REF, PARAM_SPEC])
    keys = [(op["args"]["target_id"], op["args"]["param"]) for op in out["ops"]]
    assert keys == sorted(keys)
    values = {
        op["args"]["param"]: op["args"]["value"]
        for op in out["ops"]
        if op["args"]["target_id"] == walls[0]
    }
    assert values[PARAM_SKU] == STD_PAINT and values[PARAM_SPEC] == "09 91 23"
    assert (
        values[PARAM_MATERIAL] == "Placeholder Mfg PH-02" and values[PARAM_RENDER_REF] == "mock-ref"
    )


def test_wall_conflict_writes_comments_only_and_non_selecting_neighbour_never_conflicts():
    # two rooms sharing a wall with different SKUs (LUX tile needs an override)
    shared = None
    for wall_id in {w["id"] for w in GOLDEN_LAYOUT["walls"]}:
        rooms = [r for r in ROOMS.values() if wall_id in r["boundary_wall_ids"]]
        if len(rooms) >= 2:
            shared, (a, b) = wall_id, (rooms[0]["id"], rooms[1]["id"])
            break
    assert shared is not None
    out = run(
        empty(
            rooms=[{"room_id": a, "wall_sku": STD_PAINT}, {"room_id": b, "wall_sku": LUX_TILE}],
            overrides=[{"target": b, "sku": LUX_TILE, "reason": "wet room tile"}],
        )
    )
    assert out["blocking"] == []
    wall_ops = [op for op in out["ops"] if op["args"]["target_id"] == shared]
    assert [op["args"]["param"] for op in wall_ops] == [PARAM_COMMENTS]
    assert wall_ops[0]["args"]["value"] == f"finish conflict: {a} {STD_PAINT} / {b} {LUX_TILE}"
    codes = {i["code"] for i in out["review_items"]}
    assert {"wall_finish_conflict", "tier_override"} <= codes
    assert out["diagnostics"]["per_target"][shared]["status"] == "conflict"
    # PIN-S2: only room a selects -> the shared wall takes a's SKU without conflict
    solo = run(empty(rooms=[{"room_id": a, "wall_sku": STD_PAINT}]))
    assert solo["diagnostics"]["per_target"][shared]["status"] == "applied"
    assert "wall_finish_conflict" not in {i["code"] for i in solo["review_items"]}


def test_tier_mismatch_blocking_vs_override_info():
    out = run(empty(rooms=[{"room_id": "R-001", "wall_sku": LUX_TILE}]))
    assert out["blocking"] == ["tier_mismatch"] and out["ops"] == []
    out = run(
        empty(
            rooms=[{"room_id": "R-001", "wall_sku": LUX_TILE}],
            overrides=[{"target": "R-001", "sku": LUX_TILE, "reason": "client asked"}],
        )
    )
    assert out["blocking"] == [] and out["ops"]
    assert any(
        i["code"] == "tier_override" and "client asked" in i["message"] for i in out["review_items"]
    )
    unused = run(
        empty(
            rooms=[{"room_id": "R-001", "wall_sku": STD_PAINT}],
            overrides=[{"target": "R-002", "sku": LUX_TILE, "reason": "x"}],
        )
    )
    assert any(i["code"] == "override_unused" for i in unused["review_items"])


def test_doors_and_plumbing_fixtures_emit_sku_and_spec_only():
    door = GOLDEN_LAYOUT["doors"][0]["id"]
    out = run(
        empty(
            doors=[{"id": door, "sku": STD_DOOR}],
            plumbing_fixtures=[{"id": WC_IDS[0], "sku": STD_WC}],
        )
    )
    assert out["blocking"] == []
    by_target = {}
    for op in out["ops"]:
        by_target.setdefault(op["args"]["target_id"], []).append(op["args"]["param"])
    assert by_target[door] == sorted([PARAM_SKU, PARAM_SPEC])
    assert by_target[WC_IDS[0]] == sorted([PARAM_SKU, PARAM_SPEC])
    assert out["diagnostics"]["per_target"][WC_IDS[0]]["category"] == "plumbing"


def test_unknown_sku_target_surface_mismatch_and_placeholder_refusal():
    out = run(
        empty(
            doors=[
                {"id": "D-999", "sku": STD_DOOR},
                {"id": GOLDEN_LAYOUT["doors"][0]["id"], "sku": "NOPE"},
            ]
        )
    )
    assert out["blocking"] == ["unknown_sku", "unknown_target"] and out["ops"] == []
    out = run(empty(doors=[{"id": GOLDEN_LAYOUT["doors"][0]["id"], "sku": STD_PAINT}]))
    assert out["blocking"] == ["surface_mismatch"]
    out = run(empty(rooms=[{"room_id": "R-001", "wall_sku": STD_PAINT}]), allow=False)
    assert out["blocking"] == ["placeholder_sku"] and out["ops"] == []
    # a door that exists in the layout but not in the id-map is not a settable element
    out = run(empty(doors=[{"id": GOLDEN_LAYOUT["doors"][0]["id"], "sku": STD_DOOR}]), ids=[])
    assert out["blocking"] == ["unknown_target"]


def test_plumbing_target_rules_hookup_default_and_appliances():
    out = run(empty(plumbing_fixtures=[{"id": BED_IDS[0], "sku": STD_WC}]))
    assert out["blocking"] == ["not_a_plumbing_fixture"]
    out = run(empty(plumbing_fixtures=[{"id": DW_IDS[0], "sku": DW}]))
    assert out["blocking"] == [] and out["ops"] == []
    assert [i["code"] for i in out["review_items"]] == ["appliance_not_selectable"]
    # hookups default from plumbing.json: strip the item's own hookups, the lav stays plumbing
    layout = copy.deepcopy(GOLDEN_LAYOUT)
    for group in layout["furniture"]:
        for item in group["items"]:
            item.pop("hookups", None)
    out = run(empty(plumbing_fixtures=[{"id": LAV_IDS[0], "sku": STD_LAV}]), layout=layout)
    assert out["blocking"] == [] and len(out["ops"]) == 2


def test_casework_targets_synthetic():
    layout = copy.deepcopy(GOLDEN_LAYOUT)
    layout["casework"] = [
        {
            "id": "K-001",
            "room_id": "R-009",
            "host_wall_id": "W-026",
            "start_offset": 0,
            "length": 1800,
            "depth": 600,
            "height": 900,
            "revit_family": "CHPT_Casework_PLACEHOLDER",
            "revit_type": "Base_PLACEHOLDER",
            "is_counter": True,
        }
    ]
    out = run(
        empty(casework=[{"id": "K-001", "sku": "CHPT-CASE-SHAKER-STD_PLACEHOLDER"}]),
        ids=IDS + ["K-001"],
        layout=layout,
    )
    assert out["blocking"] == []
    params = sorted(op["args"]["param"] for op in out["ops"])
    assert params == sorted([PARAM_MATERIAL, PARAM_SKU, PARAM_RENDER_REF, PARAM_SPEC])


def test_render_ref_optional_and_catalog_version_pinned():
    out = run(empty(rooms=[{"room_id": "R-001", "wall_sku": STD_PAINT}]), render_ref=None)
    assert out["blocking"] == []
    assert PARAM_RENDER_REF not in {op["args"]["param"] for op in out["ops"]}
    assert any(i["code"] == "render_ref_missing" for i in out["review_items"])
    out = validate_selection(GOLDEN_LAYOUT, IDS, "standard", "9.9.9", None, empty(), True)
    assert out["blocking"] == ["catalog_version_mismatch"]


def test_duplicates_and_unknown_room():
    out = run(
        empty(
            rooms=[
                {"room_id": "R-001", "wall_sku": STD_PAINT},
                {"room_id": "R-001", "wall_sku": STD_PAINT},
                {"room_id": "R-999", "wall_sku": STD_PAINT},
            ]
        )
    )
    assert out["blocking"] == ["duplicate_target", "unknown_target"]
    door = GOLDEN_LAYOUT["doors"][0]["id"]
    out = run(empty(doors=[{"id": door, "sku": STD_DOOR}, {"id": door, "sku": STD_DOOR}]))
    assert out["blocking"] == ["duplicate_target"]


def test_emitted_params_all_allowlisted_for_category_and_negative(monkeypatch):
    """PLAN acceptance: the approval -> set_parameter envelope uses only allowlisted params.
    Positive: every emitted op passes the real allowlist for the target's category.
    Negative: shrinking the allowlist turns our own emission into a blocking item + no ops."""
    out = run(
        empty(
            rooms=[{"room_id": "R-001", "wall_sku": STD_PAINT}],
            doors=[{"id": GOLDEN_LAYOUT["doors"][0]["id"], "sku": STD_DOOR}],
        )
    )
    allow = param_allowlist()
    for op in out["ops"]:
        category = sel.target_category(op["args"]["target_id"], sel.index_layout(GOLDEN_LAYOUT))
        cats = allow[op["args"]["param"]]["categories"]
        assert "*" in cats or category in cats
    shrunk = json.loads(json.dumps(allow))
    shrunk[PARAM_RENDER_REF]["categories"] = ["casework"]  # walls may no longer carry it
    monkeypatch.setattr(sel, "param_allowlist", lambda: shrunk)
    out = run(empty(rooms=[{"room_id": "R-001", "wall_sku": STD_PAINT}]))
    assert out["blocking"] == ["param_not_allowed"] and out["ops"] == []


def test_param_constants_are_in_the_allowlist_and_validate_ops_rejects_junk():
    allow = param_allowlist()
    for param in (PARAM_SKU, PARAM_SPEC, PARAM_MATERIAL, PARAM_RENDER_REF, PARAM_COMMENTS):
        assert param in allow
    with pytest.raises(SelectionError) as err:
        validate_ops(
            [{"op": "set_parameter", "args": {"target_id": "W-001", "param": "Mark", "value": "x"}}]
        )
    assert err.value.code == "selection_internal"
    with pytest.raises(SelectionError):
        validate_ops([{"op": "set_parameter", "args": {"target_id": "W-001", "param": PARAM_SKU}}])
