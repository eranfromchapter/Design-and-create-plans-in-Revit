"""SI-3: TTL is re-checked at dequeue. Valid when verified at enqueue, expired by
execution time -> accepted ack, then rolled_back with expired_ttl (never executed)."""

from conftest import FakeClock
from signing import make_body, sign_envelope, wall_op


def test_ttl_recheck_at_dequeue(make_executor):
    # enqueue check at 00:05 (valid), dequeue check at 00:30 (expired; ttl 600s)
    ex = make_executor(clock=FakeClock("2026-01-01T00:05:00Z", "2026-01-01T00:30:00Z"))
    messages = ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1)])))
    assert messages[0] == {
        "type": "ack",
        "envelope_id": messages[0]["envelope_id"],
        "status": "accepted",
    }
    assert messages[1]["status"] == "rolled_back"
    assert messages[1]["errors"][0]["code"] == "expired_ttl"
    assert ex.model.walls == {}
    assert ex.state.last_committed_seq == 0


def test_ttl_boundary_still_executes(make_executor):
    # dequeue exactly at expiry (00:10:00 for ttl 600) is boundary-inclusive
    ex = make_executor(clock=FakeClock("2026-01-01T00:05:00Z", "2026-01-01T00:10:00Z"))
    messages = ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1)])))
    assert messages[-1]["status"] == "committed"
