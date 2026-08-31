"""Goldens are byte-compared: the renderer must emit identical bytes for the same
model regardless of insertion order (canonical-by-construction, amendment delivery-8)."""

from revit_sim.model import Catalogs, SimModel
from revit_sim.render.svg import render_plan

CATALOGS = Catalogs.load()


def build(order: list[int]) -> SimModel:
    model = SimModel()
    walls = {
        1: ([0, 0], [4000, 0]),
        2: ([4000, 0], [4000, 3000]),
        3: ([4000, 3000], [0, 3000]),
        4: ([0, 3000], [0, 0]),
    }
    for i in order:
        start, end = walls[i]
        model.apply(
            "create_wall",
            {
                "id": f"W-{i:03d}",
                "start": start,
                "end": end,
                "revit_type": "CHPT_Partition_92mm_PLACEHOLDER",
                "height": 2700,
                "phase": "new",
            },
            CATALOGS,
        )
    model.apply(
        "create_door",
        {
            "id": "D-001",
            "host_wall_id": "W-001",
            "offset": 1000,
            "revit_type": "CHPT_Door_Single_PLACEHOLDER",
            "width": 813,
            "height": 2032,
            "swing": "L",
        },
        CATALOGS,
    )
    return model


def test_insertion_order_does_not_change_bytes():
    assert render_plan(build([1, 2, 3, 4])) == render_plan(build([4, 2, 1, 3]))


def test_svg_is_stable_and_parseable():
    import xml.etree.ElementTree as ET

    svg = render_plan(build([1, 2, 3, 4]))
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    ids = [el.get("data-id") for el in root]
    assert ids == ["W-001", "W-002", "W-003", "W-004", "D-001"]
    assert render_plan(build([1, 2, 3, 4])) == svg  # rerender identical
