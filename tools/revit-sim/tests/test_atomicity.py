"""Per-envelope atomicity (SI-5): a mid-envelope failure rolls back EVERYTHING, the
seq is not consumed, element ids are not burned, and a re-issued envelope commits
with the same ids a clean run would have produced."""

from signing import make_body, sign_envelope, wall_op


def test_mid_envelope_failure_rolls_back_everything(make_executor):
    ex = make_executor()
    # op 3 duplicates W-001 -> whole envelope must roll back
    body = make_body(1, [wall_op(1), wall_op(2, y=1000), wall_op(1)])
    messages = ex.handle_envelope(sign_envelope(body))

    assert [m["type"] for m in messages] == ["ack", "commit_result"]
    assert messages[0]["status"] == "accepted"
    result = messages[1]
    assert result["status"] == "rolled_back"
    assert result["errors"] == [{"op_index": 2, "code": "duplicate_id", "message": "W-001"}]
    assert result["id_map_delta"] == []
    assert ex.model.walls == {}
    assert ex.state.last_committed_seq == 0
    assert ex.state.id_map == {}


def test_seq_reissue_after_rollback_produces_identical_ids(make_executor):
    ex = make_executor()
    ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1), wall_op(1)])))  # rolls back
    messages = ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1), wall_op(2, y=1000)])))
    result = messages[-1]
    assert result["status"] == "committed"
    assert result["id_map_delta"] == [
        {"logical_id": "W-001", "element_id": 1000001},
        {"logical_id": "W-002", "element_id": 1000002},
    ]
    assert ex.state.last_committed_seq == 1


def test_two_envelopes_second_fails_first_survives(make_executor):
    ex = make_executor()
    first = ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1)])))
    assert first[-1]["status"] == "committed"
    second = ex.handle_envelope(sign_envelope(make_body(2, [wall_op(2, y=500), wall_op(1)])))
    assert second[-1]["status"] == "rolled_back"
    assert set(ex.model.walls) == {"W-001"}
    assert ex.state.last_committed_seq == 1


def test_interference_rolls_back_with_clash_delta(make_executor):
    ex = make_executor()
    fam = lambda i, cx: {  # noqa: E731
        "op": "place_family",
        "args": {
            "id": f"F-{i:03d}",
            "revit_family": "CHPT_Sofa_PLACEHOLDER",
            "revit_type": "CHPT_Sofa_PLACEHOLDER",
            "center": [cx, 0],
            "rotation_deg": 0,
            "footprint": [2000, 900],
            "level": "L1",
        },
    }
    body = make_body(
        1,
        [
            {"op": "create_level", "args": {"name": "L1", "elevation": 0}},
            fam(1, 0),
            fam(2, 500),  # overlapping
            {"op": "run_interference_check", "args": {"scope": "last_commit"}},
        ],
    )
    messages = ex.handle_envelope(sign_envelope(body))
    assert messages[1]["status"] == "rolled_back"
    assert messages[2]["type"] == "clash_delta"
    assert messages[2]["pairs"] == [{"a_id": "F-001", "b_id": "F-002", "kind": "hard_interference"}]
    assert ex.model.families == {}
