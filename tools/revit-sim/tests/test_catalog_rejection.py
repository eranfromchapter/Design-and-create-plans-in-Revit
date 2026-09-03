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


def test_asbuilt_opening_types_accepted(make_executor):
    """Commit #0 doors/windows carry the as-built placeholder types (Phase 2 Lane A);
    Catalogs.load unions them with the new-construction vocabulary."""
    ex = make_executor()
    host = wall_op(1, revit_type="CHPT_AsBuilt_200mm_PLACEHOLDER")
    host["args"]["phase"] = "existing"
    ops = [
        host,
        {
            "op": "create_door",
            "args": {
                "id": "D-001",
                "host_wall_id": "W-001",
                "offset": 1000,
                "revit_type": "CHPT_AsBuilt_Door_PLACEHOLDER",
                "width": 915,
                "height": 2040,
                "swing": "L",
            },
        },
        {
            "op": "create_window",
            "args": {
                "id": "N-001",
                "host_wall_id": "W-001",
                "offset": 3000,
                "sill_height": 900,
                "revit_type": "CHPT_AsBuilt_Window_PLACEHOLDER",
                "width": 1067,
                "height": 1400,
            },
        },
    ]
    messages = ex.handle_envelope(sign_envelope(make_body(1, ops)))
    assert messages[-1]["status"] == "committed"
    assert "D-001" in ex.model.doors and "N-001" in ex.model.windows


def test_unknown_door_type_rolls_back(make_executor):
    ex = make_executor()
    host = wall_op(1, revit_type="CHPT_AsBuilt_200mm_PLACEHOLDER")
    door = {
        "op": "create_door",
        "args": {
            "id": "D-001",
            "host_wall_id": "W-001",
            "offset": 1000,
            "revit_type": "Single-Flush 36x80",
            "width": 915,
            "height": 2040,
            "swing": "L",
        },
    }
    messages = ex.handle_envelope(sign_envelope(make_body(1, [host, door])))
    assert messages[-1]["status"] == "rolled_back"
    assert messages[-1]["errors"][0]["code"] == "unknown_revit_type"
    assert ex.model.walls == {} and ex.model.doors == {}


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


# ---- Phase 7 (SI-4): the allowlist scopes each parameter to categories --------------------


def _phase7_fixture(ex):
    """One committed envelope: a wall, a door, a wc (plumbing), a bed (furniture), a pipe."""
    from phase7_helpers import BED, PIPE_TYPE, WC, door_args, family_args, wall_args

    ops = [
        {"op": "create_wall", "args": wall_args(1)},
        {"op": "create_door", "args": door_args(1, "W-001", 1000)},
        {"op": "place_family", "args": family_args(1, WC[0], WC[1], [1000, 1000], WC[2])},
        {"op": "place_family", "args": family_args(2, BED[0], BED[1], [3000, 1500], BED[2])},
        {
            "op": "create_pipe",
            "args": {
                "id": "P-001",
                "system": "sanitary",
                "pipe_type": PIPE_TYPE,
                "level": "L1",
                "path": [[0, 500, -300], [4000, 500, -300]],
                "diameter": 76,
            },
        },
    ]
    messages = ex.handle_envelope(sign_envelope(make_body(1, ops)))
    assert messages[-1]["status"] == "committed"


def _set(ex, seq, target, param, value):
    op = {"op": "set_parameter", "args": {"target_id": target, "param": param, "value": value}}
    return ex.handle_envelope(sign_envelope(make_body(seq, [op])))[-1]


def test_param_allowlist_category_enforced(make_executor):
    ex = make_executor()
    _phase7_fixture(ex)
    # walls may carry a finish; doors may not
    ok = _set(ex, 2, "W-001", "CHPT_Finish_Material", "Placeholder Mfg PH-02")
    assert ok["status"] == "committed"
    rejected = _set(ex, 3, "D-001", "CHPT_Finish_Material", "x")
    assert rejected["status"] == "rolled_back"
    assert rejected["errors"][0]["code"] == "param_not_allowlisted"
    assert "doors" in rejected["errors"][0]["message"]
    # product SKUs: plumbing fixtures (wc) and furniture (bed) both allowed
    assert _set(ex, 3, "F-001", "CHPT_Product_SKU", "CHPT-WC-STD_PLACEHOLDER")["status"] == (
        "committed"
    )
    assert _set(ex, 4, "F-002", "CHPT_Product_SKU", "SKU")["status"] == "committed"
    # a finish on a plumbing fixture is not allowlisted (walls/casework only)
    rejected = _set(ex, 5, "F-001", "CHPT_Finish_Material", "x")
    assert rejected["errors"][0]["code"] == "param_not_allowlisted"
    assert "plumbing" in rejected["errors"][0]["message"]
    # Comments ("*") may touch anything, even a pipe that has no category
    note = _set(ex, 5, "P-001", "Comments", "finish conflict: R-001 a / R-002 b")
    assert note["status"] == "committed"
    assert ex.model.parameters["W-001"]["CHPT_Finish_Material"] == "Placeholder Mfg PH-02"


def test_param_value_type_sanity(make_executor):
    ex = make_executor()
    _phase7_fixture(ex)
    rejected = _set(ex, 2, "W-001", "CHPT_Product_SKU", 42)
    assert rejected["status"] == "rolled_back"
    assert rejected["errors"][0]["code"] == "param_type_mismatch"
    rejected = _set(ex, 2, "W-001", "Comments", True)
    assert rejected["errors"][0]["code"] == "param_type_mismatch"
    assert "W-001" not in ex.model.parameters
