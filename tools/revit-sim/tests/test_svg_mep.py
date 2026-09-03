"""Phase 6 renderer additions are append-only: per-kind device symbols, system-
coloured pipes, dashed conduits, a stack marker for vertical pipes. A model with
no MEP elements renders exactly as before (the layout-compiler golden pins for
phases 2/4/5 and the e2e phase-1 golden prove the bytes; here we prove the
MEP-free path emits nothing new)."""

import xml.etree.ElementTree as ET

from revit_sim.model import Catalogs, SimModel
from revit_sim.render.svg import render_plan

CATALOGS = Catalogs.load()
PIPE_TYPE = "CHPT_Pipe_PVC_DWV_PLACEHOLDER"


def walls_only() -> SimModel:
    model = SimModel()
    model.apply(
        "create_wall",
        {
            "id": "W-001",
            "start": [0, 0],
            "end": [4000, 0],
            "revit_type": "CHPT_Partition_92mm_PLACEHOLDER",
            "height": 2700,
            "phase": "new",
        },
        CATALOGS,
    )
    return model


def with_mep() -> SimModel:
    model = walls_only()
    for i, kind in enumerate(["receptacle", "gfci", "switch", "receptacle_240"], start=1):
        model.apply(
            "place_device",
            {
                "id": f"E-00{i}",
                "kind": kind,
                "host_wall_id": "W-001",
                "offset": 500 * i,
                "height_afl": 380,
                "face": "left",
            },
            CATALOGS,
        )
    model.apply(
        "create_pipe",
        {
            "id": "P-001",
            "system": "sanitary",
            "pipe_type": PIPE_TYPE,
            "level": "Level 1",
            "path": [[3500, 0, -300], [3500, 0, 2700]],
            "diameter": 76,
        },
        CATALOGS,
    )
    model.apply(
        "create_pipe",
        {
            "id": "P-002",
            "system": "sanitary",
            "pipe_type": PIPE_TYPE,
            "level": "Level 1",
            "path": [[600, 1000, -188.0], [600, 0, -162.5], [3500, 0, -150.0]],
            "diameter": 38,
        },
        CATALOGS,
    )
    model.apply(
        "create_conduit",
        {
            "id": "Q-001",
            "level": "Level 1",
            "path": [[500, 46, 380], [500, 46, 2600], [2000, 46, 2600]],
            "diameter": 21,
        },
        CATALOGS,
    )
    return model


def test_mep_free_model_has_no_mep_markup():
    svg = render_plan(walls_only())
    for marker in ("device", "pipe", "conduit", "stack", "#1f4e9c", "#e08a00"):
        assert marker not in svg
    assert render_plan(walls_only()) == svg


def test_device_symbols_per_kind_and_stack_marker():
    svg = render_plan(with_mep())
    root = ET.fromstring(svg)
    by_id = {el.get("data-id"): el for el in root}

    def tags(el: ET.Element) -> list[str]:
        return [c.tag.split("}")[-1] for c in el]  # strip the SVG namespace

    assert by_id["E-001"].get("class") == "device receptacle"
    assert tags(by_id["E-001"]) == ["circle", "line"]
    assert by_id["E-002"].get("class") == "device gfci"
    assert tags(by_id["E-002"]) == ["circle", "rect"]
    assert by_id["E-003"].get("class") == "device switch"
    assert tags(by_id["E-003"]) == ["rect", "line"]
    assert by_id["E-004"].get("class") == "device receptacle_240"
    assert tags(by_id["E-004"]) == ["circle", "circle"]
    # devices sit on the left face of the 92mm partition
    assert by_id["E-001"][0].get("cy") == "46.0"
    # the vertical pipe is a stack marker; the sloped run is a coloured polyline
    assert by_id["P-001"].get("class") == "stack sanitary"
    assert tags(by_id["P-001"]) == ["circle", "line", "line"]
    assert by_id["P-001"][0].get("r") == "78.0"  # d/2 + 40
    assert by_id["P-002"].get("class") == "pipe sanitary"
    assert by_id["P-002"].get("stroke") == "#1f4e9c"
    assert by_id["P-002"].get("stroke-width") == "38.0"  # max(diameter, 20)
    assert by_id["Q-001"].get("class") == "conduit"
    assert by_id["Q-001"].get("stroke-dasharray") == "120.0 60.0"
    # canonical order: walls, doors, windows, families, devices, pipes, conduits
    assert list(by_id) == ["W-001", "E-001", "E-002", "E-003", "E-004", "P-001", "P-002", "Q-001"]


def test_mep_render_is_deterministic():
    assert render_plan(with_mep()) == render_plan(with_mep())
