"""Build the 2BR fixture as an ezdxf document — shared by the provenance script
(scripts/gen_fixture_dxf.py) and the test suite's in-memory unit variants.
Kept inside the package so the committed DXF and the tests can never disagree
about the source geometry."""

from __future__ import annotations

import ezdxf
from ezdxf.document import Drawing

from scan_converter import fixture_2br

LAYERS = ("WALLS", "DOORS", "WINDOWS", "ROOMS")


def build_fixture_doc(insunits: int = fixture_2br.INSUNITS, scale: float = 1.0) -> Drawing:
    """The canonical fixture at `scale` (1.0 = mm; 1/25.4 = the inches variant).

    `insunits` is written to the header independently of `scale` so tests can
    produce a unitless ($INSUNITS=0) file with mm or inch coordinates.
    """
    doc = ezdxf.new(dxfversion="R2018", setup=False)
    doc.header["$INSUNITS"] = insunits
    for name in LAYERS:
        doc.layers.add(name)
    msp = doc.modelspace()

    for wall in fixture_2br.WALL_POLYLINES:
        points = [(x * scale, y * scale, b) for (x, y, b) in wall["points"]]
        msp.add_lwpolyline(
            points,
            format="xyb",
            dxfattribs={"layer": "WALLS", "const_width": wall["width"] * scale},
        )
    for start, end in fixture_2br.DOOR_LINES:
        msp.add_line(
            (start[0] * scale, start[1] * scale),
            (end[0] * scale, end[1] * scale),
            dxfattribs={"layer": "DOORS"},
        )
    for start, end in fixture_2br.WINDOW_LINES:
        msp.add_line(
            (start[0] * scale, start[1] * scale),
            (end[0] * scale, end[1] * scale),
            dxfattribs={"layer": "WINDOWS"},
        )
    for text, at in fixture_2br.ROOM_LABELS:
        attribs = {"layer": "ROOMS", "insert": (at[0] * scale, at[1] * scale)}
        msp.add_text(text, dxfattribs={**attribs, "height": 200 * scale})
    return doc
