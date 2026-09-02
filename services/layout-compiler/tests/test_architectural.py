"""Part G identity spec: kept elements verbatim (mm fields within 1mm, all else
exact), immutable walls, renumber detection, provenance, riser pass-through,
demolition-by-phasing (never delete_element), deterministic op order, and every
emitted op valid against the registry args_schema."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from layout_compiler.architectural import DiffError, diff_layouts

REPO = Path(__file__).resolve().parents[3]
REGISTRY = json.loads((REPO / "packages" / "contracts" / "ops" / "registry.json").read_text())

ASBUILT = "CHPT_AsBuilt_100mm_PLACEHOLDER"
NEW_WALL = "CHPT_Partition_92mm_PLACEHOLDER"
NEW_DOOR = "CHPT_Door_Single_PLACEHOLDER"
NEW_WINDOW = "CHPT_Window_DoubleHung_PLACEHOLDER"


def scan_wall(i: int, start: list[float], end: list[float], **over: Any) -> dict[str, Any]:
    return {
        "id": f"W-{i:03d}",
        "start": start,
        "end": end,
        "revit_type": ASBUILT,
        "height": 2700.0,
        "as_built_thickness": 100.0,
        "confidence": 0.85,
        "source": "scan",
        **over,
    }


def frozen_layout() -> dict[str, Any]:
    """A minimal frozen Commit #0: envelope of immutable walls, one demolishable
    interior partition, a door, a window, a sanitary riser."""
    return {
        "walls": [
            scan_wall(1, [0.0, 0.0], [8000.0, 0.0], is_exterior=True),
            scan_wall(2, [8000.0, 0.0], [8000.0, 6000.0], is_demising=True),
            scan_wall(3, [8000.0, 6000.0], [0.0, 6000.0], is_load_bearing=True),
            scan_wall(4, [0.0, 6000.0], [0.0, 0.0], is_exterior=True),
            scan_wall(5, [4000.0, 0.0], [4000.0, 6000.0]),
        ],
        "doors": [
            {
                "id": "D-001",
                "host_wall_id": "W-001",
                "offset": 2000.0,
                "width": 915.0,
                "height": 2040.0,
                "revit_type": "CHPT_AsBuilt_Door_PLACEHOLDER",
                "swing": "L",
            }
        ],
        "windows": [
            {
                "id": "N-001",
                "host_wall_id": "W-003",
                "offset": 3000.0,
                "width": 1200.0,
                "height": 1400.0,
                "sill_height": 900.0,
                "revit_type": "CHPT_AsBuilt_Window_PLACEHOLDER",
            }
        ],
        "risers": [{"id": "RS-01", "type": "sanitary", "center": [7800.0, 5800.0]}],
    }


def new_wall(i: int, start: list[float], end: list[float], **over: Any) -> dict[str, Any]:
    return {
        "id": f"W-{i:03d}",
        "start": start,
        "end": end,
        "revit_type": NEW_WALL,
        "height": 2700.0,
        "source": "generated",
        **over,
    }


def violation_text(err: pytest.ExceptionInfo[DiffError]) -> str:
    return "\n".join(err.value.violations)


def test_identical_layouts_produce_no_ops():
    frozen = frozen_layout()
    result = diff_layouts(frozen, copy.deepcopy(frozen))
    assert result.ops == []
    assert result.demolition == []


def test_kept_wall_within_epsilon_accepted():
    frozen = frozen_layout()
    new = copy.deepcopy(frozen)
    new["walls"][1]["start"] = [8000.5, 0.0]  # 0.5mm <= EPSILON_MM
    assert diff_layouts(frozen, new).ops == []


def test_kept_wall_perturbed_2mm_rejected_never_demolish_and_create():
    frozen = frozen_layout()
    new = copy.deepcopy(frozen)
    new["walls"][1]["start"] = [8002.0, 0.0]
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, new)
    assert err.value.code == "identity_violation"
    assert "walls.W-002" in violation_text(err)


def test_kept_wall_flag_drop_rejected():
    frozen = frozen_layout()
    new = copy.deepcopy(frozen)
    del new["walls"][1]["is_demising"]
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, new)
    assert "drops field 'is_demising'" in violation_text(err)


def test_kept_wall_type_change_rejected():
    frozen = frozen_layout()
    new = copy.deepcopy(frozen)
    new["walls"][4]["revit_type"] = "CHPT_AsBuilt_150mm_PLACEHOLDER"
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, new)
    assert "differs on 'revit_type'" in violation_text(err)


def test_kept_door_offset_perturbed_rejected_within_epsilon_accepted():
    frozen = frozen_layout()
    ok = copy.deepcopy(frozen)
    ok["doors"][0]["offset"] = 2000.9
    assert diff_layouts(frozen, ok).ops == []
    bad = copy.deepcopy(frozen)
    bad["doors"][0]["offset"] = 2002.0
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, bad)
    assert "doors.D-001" in violation_text(err)


def test_immutable_wall_omission_rejected():
    frozen = frozen_layout()
    new = copy.deepcopy(frozen)
    new["walls"] = [w for w in new["walls"] if w["id"] != "W-002"]  # is_demising
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, new)
    assert "immutable existing wall (is_demising)" in violation_text(err)


def test_renumbered_wall_rejected_both_orientations():
    frozen = frozen_layout()
    for start, end in (
        ([4000.0, 0.0], [4000.0, 6000.0]),
        ([4000.0, 6000.0], [4000.0, 0.0]),  # reversed vertex order is the same wall
    ):
        new = copy.deepcopy(frozen)
        new["walls"] = [w for w in new["walls"] if w["id"] != "W-005"]
        new["walls"].append(new_wall(105, start, end))
        with pytest.raises(DiffError) as err:
            diff_layouts(frozen, new)
        assert "reappears as W-105" in violation_text(err)


def test_renumbered_door_rejected():
    frozen = frozen_layout()
    new = copy.deepcopy(frozen)
    door = new["doors"][0]
    new["doors"] = [{**door, "id": "D-101", "revit_type": NEW_DOOR}]
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, new)
    assert "doors.D-001: existing element reappears as D-101" in violation_text(err)


def test_new_wall_with_scan_source_rejected():
    frozen = frozen_layout()
    new = copy.deepcopy(frozen)
    new["walls"].append(scan_wall(106, [1000.0, 0.0], [1000.0, 6000.0]))
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, new)
    assert 'walls.W-106: new wall must have source="generated"' in violation_text(err)


def test_riser_pass_through_enforced():
    frozen = frozen_layout()
    moved = copy.deepcopy(frozen)
    moved["risers"][0]["center"] = [7802.0, 5800.0]
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, moved)
    assert "risers.RS-01: riser mutated" in violation_text(err)

    dropped = copy.deepcopy(frozen)
    dropped["risers"] = []
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, dropped)
    assert "risers.RS-01: existing riser missing" in violation_text(err)

    invented = copy.deepcopy(frozen)
    invented["risers"].append({"id": "RS-02", "type": "vent", "center": [100.0, 100.0]})
    with pytest.raises(DiffError) as err:
        diff_layouts(frozen, invented)
    assert "risers.RS-02: new riser invented" in violation_text(err)


def test_absent_elements_demolished_by_phasing_never_deleted():
    frozen = frozen_layout()
    new = copy.deepcopy(frozen)
    new["walls"] = [w for w in new["walls"] if w["id"] != "W-005"]
    result = diff_layouts(frozen, new)
    assert result.ops == [{"op": "set_phase_demolished", "args": {"target_id": "W-005"}}]
    assert result.demolition == [{"kind": "wall", "id": "W-005"}]
    assert all(op["op"] != "delete_element" for op in result.ops)


def mixed_scenario() -> tuple[dict[str, Any], dict[str, Any]]:
    """Demolish D-001, N-001, W-005; create W-101 (wet), D-101 on W-101,
    N-101 on kept W-001 — positioned away from any demolished element."""
    frozen = frozen_layout()
    new = copy.deepcopy(frozen)
    new["walls"] = [w for w in new["walls"] if w["id"] != "W-005"]
    new["doors"] = []
    new["windows"] = []
    new["walls"].append(new_wall(101, [2000.0, 0.0], [2000.0, 6000.0], is_wet_wall=True))
    new["doors"].append(
        {
            "id": "D-101",
            "host_wall_id": "W-101",
            "offset": 1500.0,
            "width": 762.0,
            "height": 2040.0,
            "revit_type": NEW_DOOR,
        }
    )
    new["windows"].append(
        {
            "id": "N-101",
            "host_wall_id": "W-001",
            "offset": 6000.0,
            "width": 1200.0,
            "height": 1400.0,
            "sill_height": 900.0,
            "revit_type": NEW_WINDOW,
        }
    )
    return frozen, new


def test_deterministic_op_order_demolition_then_creation():
    frozen, new = mixed_scenario()
    result = diff_layouts(frozen, new)
    op_ids = [(op["op"], op["args"].get("target_id") or op["args"].get("id")) for op in result.ops]
    assert op_ids == [
        ("set_phase_demolished", "D-001"),  # openings before their hosts
        ("set_phase_demolished", "N-001"),
        ("set_phase_demolished", "W-005"),
        ("create_wall", "W-101"),  # hosts before openings
        ("create_door", "D-101"),
        ("create_window", "N-101"),
    ]
    assert result.demolition == [
        {"kind": "door", "id": "D-001"},
        {"kind": "window", "id": "N-001"},
        {"kind": "wall", "id": "W-005"},
    ]
    create_wall = result.ops[3]["args"]
    assert create_wall["phase"] == "new"
    assert create_wall["flags"] == {"is_wet_wall": True}  # flat layout flags -> nested op flags
    assert result.ops[4]["args"]["swing"] == "L"  # default when the layout omits swing
    assert result.ops[4]["args"]["flip_facing"] is False  # default when the layout omits it


def test_flip_facing_rides_in_create_door_ops():
    """The committed op is the executor's only source of leaf orientation, and
    Phase 5's swing arcs are computed from this exact field — a flipped door
    must carry flip_facing=true into the op, verbatim."""
    frozen, new = mixed_scenario()
    new["doors"][0]["flip_facing"] = True
    result = diff_layouts(frozen, new)
    (door_op,) = [op for op in result.ops if op["op"] == "create_door"]
    assert door_op["args"]["flip_facing"] is True
    jsonschema.validate(door_op["args"], REGISTRY["ops"]["create_door"]["args_schema"])


def test_emitted_ops_validate_against_registry_schemas():
    frozen, new = mixed_scenario()
    for op in diff_layouts(frozen, new).ops:
        jsonschema.validate(op["args"], REGISTRY["ops"][op["op"]]["args_schema"])
