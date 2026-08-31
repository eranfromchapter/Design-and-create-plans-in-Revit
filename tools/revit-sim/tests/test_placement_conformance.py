"""Sim-vs-plugin placement cross-check (Phase 1 acceptance, amendment revit-6): the
Python side of the shared fixture. The C# twin is PlacementConformanceTests.cs."""

import json
from pathlib import Path

import pytest

from revit_sim.placement import place

CASES = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "contracts"
        / "fixtures"
        / "placement"
        / "manifest.json"
    ).read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_placement_case(case):
    x, y, z = place(
        case["kind"],
        tuple(case["wall"]["start"]),
        tuple(case["wall"]["end"]),
        case["wall"]["thickness_mm"],
        case["offset_mm"],
        case["z_mm"],
    )
    ex, ey = case["expected_point_mm"]
    assert abs(x - ex) < 1e-6
    assert abs(y - ey) < 1e-6
    assert z == case["z_mm"]
