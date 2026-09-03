"""Phase 7 export path (docs/PHASE7_DESIGN.md P7-01): one export_ready per view IN views
ORDER after commit_result committed, content-addressed refs, PNGs at the requested px, the
view name never on the wire; debug PNGs only when the envelope commits."""

import hashlib
import json
import struct

from phase7_helpers import wall_args
from signing import make_body, sign_envelope

VIEWS = [
    {"name": "plan", "kind": "plan", "px": 256},
    {"name": "section", "kind": "section", "px": 512},
    {"name": "3d hidden/iso", "kind": "3d_hidden", "px": 300},
]


def _walls():
    return [{"op": "create_wall", "args": wall_args(i)} for i in (1, 2, 3, 4)]


def _png_width(png: bytes) -> int:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">I", png[16:20])[0]


def test_export_views_emits_one_frame_per_view_in_order_after_commit(make_executor):
    ex = make_executor()
    ops = [*_walls(), {"op": "export_views", "args": {"views": VIEWS}}]
    messages = ex.handle_envelope(sign_envelope(make_body(1, ops)))
    assert [m["type"] for m in messages] == ["ack", "commit_result"] + ["export_ready"] * 3
    assert messages[1]["status"] == "committed"
    frames = messages[2:]
    for view, frame in zip(VIEWS, frames, strict=True):
        assert frame == {"type": "export_ready", "kind": "view", "blob_ref": frame["blob_ref"]}
        png = (ex.blob_dir / frame["blob_ref"]).read_bytes()
        assert hashlib.sha256(png).hexdigest() == frame["blob_ref"]
        assert _png_width(png) == view["px"]
    assert "name" not in json.dumps(messages)
    # three distinct renderings (plan / section / axon differ)
    assert len({f["blob_ref"] for f in frames}) == 3


def test_export_debug_pngs_written_at_commit_with_safe_names(make_executor):
    ex = make_executor()
    ops = [*_walls(), {"op": "export_views", "args": {"views": VIEWS}}]
    ex.handle_envelope(sign_envelope(make_body(1, ops)))
    names = sorted(p.name for p in ex.blob_dir.glob("export_*.png"))
    assert names == ["export_3d_hidden_iso.png", "export_plan.png", "export_section.png"]
    assert (ex.blob_dir / "current_plan.svg").exists()


def test_export_views_rolled_back_emits_nothing_and_writes_no_debug_png(make_executor):
    ex = make_executor()
    bad = {"op": "create_wall", "args": {**wall_args(1), "id": "W-009", "revit_type": "Invented"}}
    ops = [*_walls(), {"op": "export_views", "args": {"views": VIEWS}}, bad]
    messages = ex.handle_envelope(sign_envelope(make_body(1, ops)))
    assert [m["type"] for m in messages] == ["ack", "commit_result"]
    assert messages[1]["status"] == "rolled_back"
    assert list(ex.blob_dir.glob("export_*.png")) == []
    # nor a content-addressed blob: in CI/e2e this directory IS the gateway's blob store
    stored = list(ex.blob_dir.iterdir()) if ex.blob_dir.exists() else []
    assert [p.name for p in stored if len(p.name) == 64] == []


def test_export_parameters_unchanged(make_executor):
    ex = make_executor()
    ops = [*_walls(), {"op": "export_parameters", "args": {"categories": ["walls"]}}]
    messages = ex.handle_envelope(sign_envelope(make_body(1, ops)))
    assert [m["type"] for m in messages] == ["ack", "commit_result", "export_ready"]
    assert messages[2]["kind"] == "parameters"
