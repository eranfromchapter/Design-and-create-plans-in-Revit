"""In-memory DXF builders shared by the test suite (same pattern as revit-sim's
tests/signing.py — pytest puts this directory on sys.path). Synthetic only (SI-11)."""

from __future__ import annotations

import io

import ezdxf

PROJECT_ID = "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01"


def doc_bytes(doc) -> bytes:
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def empty_doc(insunits: int = 4):
    doc = ezdxf.new(dxfversion="R2018", setup=False)
    doc.header["$INSUNITS"] = insunits
    for layer in ("WALLS", "DOORS", "WINDOWS", "ROOMS"):
        doc.layers.add(layer)
    return doc


def add_wall(doc, points, width: float, layer: str = "WALLS"):
    """points: (x, y) or (x, y, bulge) tuples."""
    pts = [(p[0], p[1], p[2] if len(p) > 2 else 0.0) for p in points]
    doc.modelspace().add_lwpolyline(
        pts, format="xyb", dxfattribs={"layer": layer, "const_width": width}
    )
    return doc


def add_line(doc, start, end, layer: str):
    doc.modelspace().add_line(start, end, dxfattribs={"layer": layer})
    return doc
