"""Catalog-membership rejection: the sim mirrors the plugin's real failure mode —
an LLM-invented revit_type fails the commit (amendment critic-6), it cannot pass CI."""

from signing import make_body, sign_envelope, wall_op


def test_unknown_wall_type_rolls_back(make_executor):
    ex = make_executor()
    body = make_body(1, [wall_op(1, revit_type='Generic - 4" Partition')])
    messages = ex.handle_envelope(sign_envelope(body))
    assert messages[-1]["status"] == "rolled_back"
    assert messages[-1]["errors"][0]["code"] == "unknown_revit_type"
    assert ex.model.walls == {}


def test_param_allowlist_enforced(make_executor):
    ex = make_executor()
    ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1)])))
    body = make_body(
        2,
        [
            {
                "op": "set_parameter",
                "args": {"target_id": "W-001", "param": "STRUCTURAL_DEPTH", "value": 999},
            }
        ],
    )
    messages = ex.handle_envelope(sign_envelope(body))
    assert messages[-1]["status"] == "rolled_back"
    assert messages[-1]["errors"][0]["code"] == "param_not_allowlisted"


def test_existing_walls_are_immutable(make_executor):
    """SI-8: delete/update valid only for generated elements."""
    ex = make_executor()
    existing = wall_op(1)
    existing["args"]["phase"] = "existing"
    ex.handle_envelope(sign_envelope(make_body(1, [existing])))

    delete = make_body(2, [{"op": "delete_element", "args": {"target_id": "W-001"}}])
    messages = ex.handle_envelope(sign_envelope(delete))
    assert messages[-1]["status"] == "rolled_back"
    assert messages[-1]["errors"][0]["code"] == "immutable_existing"
    assert "W-001" in ex.model.walls

    # set_phase_demolished remains the sanctioned removal path
    demo = make_body(2, [{"op": "set_phase_demolished", "args": {"target_id": "W-001"}}])
    assert ex.handle_envelope(sign_envelope(demo))[-1]["status"] == "committed"
    assert "W-001" in ex.model.demolished
