"""Phase 6 MEP ops in the sim: place_device hosts on the NAMED face at the host's
catalog thickness (the registry now requires `face`), create_pipe enforces the
pipe-type vocabulary and positive segment lengths, delete_element covers pipes
and conduits. Everything goes through signed envelopes so the registry change is
proven live in the verifier too."""

from signing import make_body, sign_envelope, wall_op

PIPE_TYPE = "CHPT_Pipe_PVC_DWV_PLACEHOLDER"


def device(face: str = "right", kind: str = "receptacle", with_face: bool = True) -> dict:
    args = {
        "id": "E-001",
        "kind": kind,
        "host_wall_id": "W-001",
        "offset": 1000,
        "height_afl": 380,
    }
    if with_face:
        args["face"] = face
    return {"op": "place_device", "args": args}


def pipe(path: list[list[float]], pipe_type: str = PIPE_TYPE, pipe_id: str = "P-001") -> dict:
    return {
        "op": "create_pipe",
        "args": {
            "id": pipe_id,
            "system": "sanitary",
            "pipe_type": pipe_type,
            "level": "Level 1",
            "path": path,
            "diameter": 76,
        },
    }


def conduit(path: list[list[float]], conduit_id: str = "Q-001") -> dict:
    return {
        "op": "create_conduit",
        "args": {"id": conduit_id, "level": "Level 1", "path": path, "diameter": 21},
    }


def test_device_hosts_on_the_named_face_at_catalog_thickness(make_executor, tmp_path):
    ex = make_executor()
    # W-001 runs (0,0)->(4000,0): left normal is +y; a 92mm partition puts faces at y=+/-46
    messages = ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1), device("right")])))
    assert messages[-1]["status"] == "committed"
    assert ex.model.devices["E-001"]["point"] == (1000.0, -46.0, 380)
    ex2 = make_executor(state_dir=tmp_path / "left-face")  # fresh persisted seq
    ex2.handle_envelope(sign_envelope(make_body(1, [wall_op(1), device("left")])))
    assert ex2.model.devices["E-001"]["point"] == (1000.0, 46.0, 380)


def test_device_without_face_is_rejected_by_the_verifier(make_executor):
    """`face` is REQUIRED in the registry args_schema: the envelope never executes."""
    ex = make_executor()
    messages = ex.handle_envelope(
        sign_envelope(make_body(1, [wall_op(1), device(with_face=False)]))
    )
    assert messages[0]["status"] == "rejected"
    assert ex.model.devices == {}


def test_receptacle_240_is_a_legal_kind(make_executor):
    ex = make_executor()
    messages = ex.handle_envelope(
        sign_envelope(make_body(1, [wall_op(1), device(kind="receptacle_240")]))
    )
    assert messages[-1]["status"] == "committed"


def test_unknown_pipe_type_rolls_back(make_executor):
    ex = make_executor()
    messages = ex.handle_envelope(
        sign_envelope(make_body(1, [pipe([[0, 0, -300], [0, 0, 2700]], pipe_type="PVC 3in")]))
    )
    assert messages[-1]["status"] == "rolled_back"
    assert messages[-1]["errors"][0]["code"] == "unknown_revit_type"


def test_zero_length_segment_rolls_back_pipe_and_conduit(make_executor):
    ex = make_executor()
    bad_pipe = ex.handle_envelope(
        sign_envelope(make_body(1, [pipe([[0, 0, -300], [0, 0, -300], [0, 0, 2700]])]))
    )
    assert bad_pipe[-1]["status"] == "rolled_back"
    assert bad_pipe[-1]["errors"][0]["code"] == "invalid_path"
    bad_conduit = ex.handle_envelope(
        sign_envelope(make_body(1, [conduit([[100, 0, 380], [100, 0, 380]])]))
    )
    assert bad_conduit[-1]["status"] == "rolled_back"
    assert bad_conduit[-1]["errors"][0]["code"] == "invalid_path"
    assert ex.model.pipes == {} and ex.model.conduits == {}


def test_valid_pipe_and_conduit_commit_and_delete(make_executor):
    ex = make_executor()
    ops = [
        pipe([[600, 4225, -188.0], [600, 6675, -162.5]]),
        conduit([[100, 0, 380], [100, 0, 2600], [3000, 0, 2600]]),
    ]
    committed = ex.handle_envelope(sign_envelope(make_body(1, ops)))
    assert committed[-1]["status"] == "committed"
    assert [d["logical_id"] for d in committed[-1]["id_map_delta"]] == ["P-001", "Q-001"]
    deleted = ex.handle_envelope(
        sign_envelope(
            make_body(
                2,
                [
                    {"op": "delete_element", "args": {"target_id": "P-001"}},
                    {"op": "delete_element", "args": {"target_id": "Q-001"}},
                ],
            )
        )
    )
    assert deleted[-1]["status"] == "committed"
    assert ex.model.pipes == {} and ex.model.conduits == {}
