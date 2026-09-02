"""Phase 5 validator furniture checks — all no-ops on furniture: [] (the whole
Phase 4 suite is that proof); each rule gets a named failing case here."""

from __future__ import annotations

from typing import Any

from helpers import make_layout

from layout_compiler.validator import validate_layout


def fitem(i: int, center: list[float], **over: Any) -> dict[str, Any]:
    """A valid catalog nightstand by default."""
    return {
        "id": f"F-{i:03d}",
        "kind": "table",
        "revit_family": "CHPT_Nightstand_PLACEHOLDER",
        "revit_type": "Nightstand_450x450_PLACEHOLDER",
        "center": center,
        "rotation_deg": 0.0,
        "footprint": [450.0, 450.0],
        **over,
    }


def furnished(items: list[dict[str, Any]]) -> dict[str, Any]:
    return make_layout(furniture=[{"room_id": "R-001", "items": items}])


def test_valid_catalog_furniture_passes():
    # sofa flush to the north wall's inner face (y = 3000 - 46), away from the
    # D-001 threshold at (2000, 0)
    sofa = {
        "id": "F-001",
        "kind": "sofa",
        "revit_family": "CHPT_Sofa_PLACEHOLDER",
        "revit_type": "Sofa_2100x900_PLACEHOLDER",
        "center": [2000.0, 2504.0],
        "rotation_deg": 0.0,
        "footprint": [2100.0, 900.0],
        "clearance_front": 450.0,
    }
    assert validate_layout(furnished([sofa])) == []


def test_duplicate_furniture_id_rejected():
    layout = furnished([fitem(1, [1000, 1500]), fitem(1, [3000, 1500])])
    assert any("furniture.F-001: duplicate element id" in e for e in validate_layout(layout))


def test_unknown_family_rejected():
    layout = furnished([fitem(1, [1000, 1500], revit_family="IKEA_Nightstand")])
    assert any("not in new_construction_types.json families" in e for e in validate_layout(layout))


def test_unknown_type_for_family_rejected():
    layout = furnished([fitem(1, [1000, 1500], revit_type="Nightstand_600x600_PLACEHOLDER")])
    assert any("is not a catalog type of" in e for e in validate_layout(layout))


def test_kind_must_match_family():
    layout = furnished([fitem(1, [1000, 1500], kind="bed")])
    assert any("kind 'bed' not offered by" in e for e in validate_layout(layout))


def test_footprint_pinned_to_catalog():
    layout = furnished([fitem(1, [1000, 1500], footprint=[500.0, 450.0])])
    assert any("footprint must match the catalog" in e for e in validate_layout(layout))


def test_footprint_outside_room_rejected():
    layout = furnished([fitem(1, [3900, 1500])])  # rect x 3675..4125 > 4000
    errors = validate_layout(layout)
    assert any("furniture F-001 footprint outside the room boundary" in e for e in errors)


def test_face_touching_footprint_is_legal():
    # east wall is a 92mm partition on x=4000: inner face at 3954; rect x 3504..3954 is flush
    layout = furnished([fitem(1, [3729, 1500])])
    assert validate_layout(layout) == []


def test_footprint_inside_a_wall_half_thickness_rejected():
    """Flush to the CENTERLINE (rect 3550..4000) sinks 46mm into the east wall's
    slab: inside the D1 boundary polygon, outside the room's inner face."""
    layout = furnished([fitem(1, [3775, 1500])])
    errors = validate_layout(layout)
    assert any("furniture F-001 footprint outside the room boundary" in e for e in errors)


def test_pairwise_overlap_rejected_touching_legal():
    overlapping = furnished([fitem(1, [1000, 1500]), fitem(2, [1300, 1500])])  # 150mm bite
    errors = validate_layout(overlapping)
    assert any("furniture.F-001~F-002: footprints overlap" in e for e in errors)

    touching = furnished([fitem(1, [1000, 1500]), fitem(2, [1450, 1500])])  # shared edge
    assert validate_layout(touching) == []


def test_furniture_blocking_the_door_fails_circulation():
    sofa = {
        "id": "F-001",
        "kind": "sofa",
        "revit_family": "CHPT_Sofa_PLACEHOLDER",
        "revit_type": "Sofa_2100x900_PLACEHOLDER",
        "center": [2000.0, 450.0],  # parked across D-001's threshold at (2000, 0)
        "rotation_deg": 0.0,
        "footprint": [2100.0, 900.0],
        "clearance_front": 450.0,
    }
    errors = validate_layout(furnished([sofa]))
    assert any("unreachable from the room's circulation space" in e for e in errors)
