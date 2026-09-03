"""TestHooks.inject_clash — the deterministic Phase-B stimulus: absent by default,
constructed only with a control port, consumed one check at a time, ignored for
unknown ids, cleared with n=0; frames arrive in the order [ack, commit_result,
clash_delta] exactly like a real interference."""

from pathlib import Path

from signing import PROJECT_ID, PUBLIC_HEX, WORKSTATION_ID, make_body, sign_envelope, wall_op

from revit_sim.client import SimClient
from revit_sim.executor import Executor, TestHooks
from revit_sim.state import SimState

CHECK = {"op": "run_interference_check", "args": {"scope": "last_commit"}}


def family_op(fid: str, center: list[float]) -> dict:
    return {
        "op": "place_family",
        "args": {
            "id": fid,
            "revit_family": "CHPT_Nightstand_PLACEHOLDER",
            "revit_type": "Nightstand_450x450_PLACEHOLDER",
            "center": center,
            "rotation_deg": 0.0,
            "footprint": [450.0, 450.0],
            "level": "Level 1",
        },
    }


def test_hooks_absent_by_default(tmp_path: Path):
    ex = Executor(
        state=SimState.load(tmp_path / "state"),
        blob_dir=tmp_path / "blobs",
        project_id=PROJECT_ID,
        workstation_id=WORKSTATION_ID,
        public_key_hex=PUBLIC_HEX,
    )
    assert ex.test_hooks is None
    assert SimClient("ws://x", "t", "ws", tmp_path, tmp_path).test_hooks is None
    with_port = SimClient("ws://x", "t", "ws", tmp_path, tmp_path, control_port=0)
    assert with_port.test_hooks == TestHooks()


def test_injected_clash_fires_n_times_then_the_real_law_applies(make_executor):
    ex = make_executor()
    ex.test_hooks = TestHooks(clash_remaining=2, clash_pair=("W-001", "W-002"))
    ops = [wall_op(1), wall_op(2, y=3000.0), CHECK]
    for _ in range(2):
        messages = ex.handle_envelope(sign_envelope(make_body(1, ops)))
        assert [m["type"] for m in messages] == ["ack", "commit_result", "clash_delta"]
        assert messages[1]["status"] == "rolled_back"
        assert messages[1]["errors"][0]["code"] == "interference"
        assert messages[1]["errors"][0]["message"] == "W-001~W-002"
        assert messages[2]["pairs"] == [
            {"a_id": "W-001", "b_id": "W-002", "kind": "hard_interference"}
        ]
        assert ex.model.walls == {}  # nothing partial
    assert ex.test_hooks.clash_remaining == 0
    # the real law now applies — with REAL clash elements in the envelope: two families
    # that touch (legal, strict <) commit; the injected pair is spent
    touching = [
        wall_op(1),
        wall_op(2, y=3000.0),
        family_op("F-001", [1000.0, 1000.0]),
        family_op("F-002", [1450.0, 1000.0]),  # 450 wide: shares an edge, no overlap
        CHECK,
    ]
    third = ex.handle_envelope(
        sign_envelope(make_body(1, touching))
    )  # same seq: rollbacks burn nothing
    assert third[-1]["status"] == "committed"
    assert set(ex.model.walls) == {"W-001", "W-002"}
    # ...and an overlapping family is caught by the law itself (not by the hook): the
    # created F-003 sits on the committed F-001 -> created-first pair
    fourth = ex.handle_envelope(
        sign_envelope(make_body(2, [family_op("F-003", [1200.0, 1000.0]), CHECK]))
    )
    assert fourth[1]["status"] == "rolled_back"
    assert fourth[1]["errors"][0]["code"] == "interference"
    assert fourth[1]["errors"][0]["message"] == "F-003~F-001"
    assert "F-003" not in ex.model.families


def test_injected_pair_with_unknown_ids_is_ignored(make_executor):
    ex = make_executor()
    ex.test_hooks = TestHooks(clash_remaining=1, clash_pair=("W-001", "E-999"))
    messages = ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1), CHECK])))
    assert messages[-1]["status"] == "committed"
    assert ex.test_hooks.clash_remaining == 1  # not consumed


def test_cleared_hooks_do_nothing(make_executor):
    ex = make_executor()
    ex.test_hooks = TestHooks(clash_remaining=0, clash_pair=None)
    messages = ex.handle_envelope(sign_envelope(make_body(1, [wall_op(1), CHECK])))
    assert messages[-1]["status"] == "committed"
