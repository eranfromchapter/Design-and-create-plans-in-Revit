"""Restart resync: seq + id-map persist atomically; a new executor over the same
state dir reports the committed truth in hello (the gateway resumes from it)."""

from chapter_contracts import id_map_hash
from signing import make_body, sign_envelope, wall_op


def test_hello_after_restart_reports_persisted_state(make_executor, tmp_path):
    ex1 = make_executor(state_dir=tmp_path / "sim")
    ex1.handle_envelope(sign_envelope(make_body(1, [wall_op(1), wall_op(2, y=1000)])))
    assert ex1.state.last_committed_seq == 1

    # "restart": a fresh executor over the same state dir
    ex2 = make_executor(state_dir=tmp_path / "sim")
    hello = ex2.hello()
    assert hello["last_committed_seq"] == 1
    assert hello["id_map_hash"] == id_map_hash({"W-001": 1000001, "W-002": 1000002})
    # replay of the already-committed envelope is refused after restart (SI-3)
    replay = ex2.handle_envelope(sign_envelope(make_body(1, [wall_op(1)])))
    assert replay[0]["reason"] == "bad_seq"


def test_rollback_does_not_persist(make_executor, tmp_path):
    ex1 = make_executor(state_dir=tmp_path / "sim")
    ex1.handle_envelope(sign_envelope(make_body(1, [wall_op(1), wall_op(1)])))  # rolled back
    ex2 = make_executor(state_dir=tmp_path / "sim")
    assert ex2.hello()["last_committed_seq"] == 0
    assert ex2.state.id_map == {}
