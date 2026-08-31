"""Entity-wise drift protection for the committed fixture DXF. Byte-comparing a
regenerated file is not viable (ezdxf stamps $VERSIONGUID/$TDUPDATE on every
save), so this compares the committed file's entities against fixture_2br.py —
the same guarantee, headers ignored."""

from __future__ import annotations

from pathlib import Path

import ezdxf

from scan_converter import fixture_2br

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "scans" / "2br_uws.dxf"


def _lines(msp, layer: str) -> set[tuple[tuple[float, float], tuple[float, float]]]:
    out = set()
    for e in msp.query(f'LINE[layer=="{layer}"]'):
        out.add(
            (
                (round(e.dxf.start.x, 3), round(e.dxf.start.y, 3)),
                (round(e.dxf.end.x, 3), round(e.dxf.end.y, 3)),
            )
        )
    return out


def test_committed_fixture_matches_spec():
    doc = ezdxf.readfile(FIXTURE)
    msp = doc.modelspace()

    assert doc.header["$INSUNITS"] == fixture_2br.INSUNITS

    walls = []
    for e in msp.query('LWPOLYLINE[layer=="WALLS"]'):
        points = [(round(x, 3), round(y, 3), round(b, 6)) for (x, y, b) in e.get_points("xyb")]
        walls.append({"width": round(e.dxf.const_width, 3), "points": points})
    expected_walls = [
        {
            "width": w["width"],
            "points": [(x, y, b) for (x, y, b) in w["points"]],
        }
        for w in fixture_2br.WALL_POLYLINES
    ]
    assert sorted(walls, key=str) == sorted(expected_walls, key=str)

    assert _lines(msp, "DOORS") == {((s[0], s[1]), (e[0], e[1])) for s, e in fixture_2br.DOOR_LINES}
    assert _lines(msp, "WINDOWS") == {
        ((s[0], s[1]), (e[0], e[1])) for s, e in fixture_2br.WINDOW_LINES
    }

    labels = {
        (e.dxf.text, (round(e.dxf.insert.x, 3), round(e.dxf.insert.y, 3)))
        for e in msp.query('TEXT[layer=="ROOMS"]')
    }
    assert labels == {(t, at) for t, at in fixture_2br.ROOM_LABELS}
