"""Wire-level negatives with the plugin's exact semantics: rejected envelopes ack
with the contract reason and NOTHING is partially applied."""

from signing import make_body, sign_envelope, wall_op


def assert_rejected(messages, reason):
    assert len(messages) == 1
    assert messages[0]["type"] == "ack"
    assert messages[0]["status"] == "rejected"
    assert messages[0]["reason"] == reason


def test_tampered_payload(make_executor):
    ex = make_executor()
    wire = sign_envelope(make_body(1, [wall_op(1)]))
    wire["payload"] = wire["payload"].replace("W-001", "W-002", 1)
    assert_rejected(ex.handle_envelope(wire), "bad_signature")
    assert ex.model.walls == {}


def test_replayed_seq(make_executor):
    ex = make_executor()
    first = ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1)])))
    assert first[-1]["status"] == "committed"
    assert_rejected(ex.handle_envelope(sign_envelope(make_body(1, [wall_op(2)]))), "bad_seq")
    assert "W-002" not in ex.model.walls


def test_expired_ttl_at_enqueue(make_executor):
    from conftest import FakeClock

    ex = make_executor(clock=FakeClock("2026-01-01T01:00:00Z"))
    assert_rejected(ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1)]))), "expired_ttl")


def test_unknown_op(make_executor):
    ex = make_executor()
    body = make_body(1, [{"op": "drop_all_walls", "args": {}}])
    assert_rejected(ex.handle_envelope(sign_envelope(body)), "unknown_op")


def test_invalid_args(make_executor):
    ex = make_executor()
    body = make_body(1, [{"op": "create_level", "args": {"name": "L1"}}])
    assert_rejected(ex.handle_envelope(sign_envelope(body)), "invalid_args")


def test_wrong_workstation(make_executor):
    ex = make_executor()
    body = make_body(1, [wall_op(1)], workstation_id="ws-design-02")
    assert_rejected(ex.handle_envelope(sign_envelope(body)), "wrong_workstation")


def test_wrong_project(make_executor):
    ex = make_executor()
    body = make_body(1, [wall_op(1)], project_id="00000000-9b4d-4c5e-8f70-123456789abc")
    assert_rejected(ex.handle_envelope(sign_envelope(body)), "wrong_document")
