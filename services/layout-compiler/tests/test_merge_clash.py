"""The Phase 6 merge gate (docs/PHASE6_DESIGN.md §4, PIN-24..31) on the golden 2BR:
branch union + trailing interference check, Phase A sweep with lower-priority
re-plans, Phase B injected pairs under the SHARED ≤3-round budget, the progress
guarantee (escalate → drop), stateless replay, ids that never renumber, Phase A ⊆
the sim's clash law with the same exemption table, oracle/timeout hard errors."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from mep_helpers import golden_chain, golden_plan
from shapely.geometry import LineString, Point, box

from layout_compiler.geometry import furniture_rect, pt_on_wall
from layout_compiler.mep.constants import MERGE_BUDGET
from layout_compiler.mep.ops import validate_ops
from layout_compiler.merge import gate as gate_mod
from layout_compiler.merge.clash import exempt as phase_a_exempt
from layout_compiler.merge.clash import phase_a
from layout_compiler.merge.gate import INTERFERENCE_CHECK, MergeOptions, merge
from layout_compiler.merge.prisms import Prism, build_prisms
from layout_compiler.merge.replan import MergeError
from layout_compiler.validator import validate_layout

HASH = "0" * 64
MERGE_SRC = Path(gate_mod.__file__).parent
MEP_OPS = {"create_pipe", "place_device", "create_conduit"}


def run(plan=None, used=0, iteration=1, prior=(), pairs=(), interior_layout=None):
    g = golden_chain()
    plan = plan if plan is not None else golden_plan()
    interior = {
        "review_id": "rv-interior",
        "content_hash": HASH,
        "ops": g["interior_ops"],
        "layout": interior_layout if interior_layout is not None else g["furnished"],
    }
    mep = {"review_id": "rv-mep", "content_hash": HASH, "plan": plan}
    return merge(
        g["commit0"],
        g["commit1_ops"],
        interior,
        mep,
        used,
        iteration,
        list(prior),
        list(pairs),
        MergeOptions(project_id=g["brief"]["meta"]["project_id"]),
    )


def pair(a: str, b: str) -> dict:
    return {"a_id": a, "b_id": b, "kind": "hard_interference"}


def stack(plan, index=0) -> dict:
    return plan["stacks"][index]


def stack_xy(plan, index=0) -> tuple[float, float]:
    s = stack(plan, index)
    wall = next(w for w in plan["layout"]["walls"] if w["id"] == s["wall_id"])
    return pt_on_wall(wall, s["offset"])


def forced_onto_stack(device_id: str, index=0) -> dict:
    """The approved MEP branch with one device moved onto the stack's offset — the
    Phase A trigger (a pipe(1) ~ device(4) overlap the sim would also report)."""
    plan = copy.deepcopy(golden_plan())
    s = stack(plan, index)
    for op in plan["ops"]:
        if op["op"] == "place_device" and op["args"]["id"] == device_id:
            assert op["args"]["host_wall_id"] == s["wall_id"]
            op["args"]["offset"] = s["offset"]
    return plan


def with_column(center, footprint, plan=None) -> dict:
    plan = copy.deepcopy(plan or golden_plan())
    plan["layout"]["columns"] = [
        {
            "id": "C-001",
            "center": [round(center[0], 1), round(center[1], 1)],
            "footprint": footprint,
        }
    ]
    return plan


def mep_ops_of(result) -> list[dict]:
    return [op for op in result["ops"] if op["op"] in MEP_OPS]


def ids(ops, kind: str) -> list[str]:
    return [op["args"]["id"] for op in ops if op["op"] == kind]


def item_by_id(layout, item_id):
    return next(i for e in layout["furniture"] for i in e["items"] if i["id"] == item_id)


def all_items(layout):
    return [i for e in layout["furniture"] for i in e["items"]]


# ---- clean merge -----------------------------------------------------------------


def test_clean_merge_is_interior_verbatim_then_mep_then_one_check():
    g, plan = golden_chain(), golden_plan()
    r = run()
    assert r["status"] == "clean" and r["iterations_used"] == 0 and r["actions"] == []
    assert r["ops"] == [*g["interior_ops"], *plan["ops"], INTERFERENCE_CHECK]
    assert r["interior"] == {
        "review_id": "rv-interior",
        "content_hash": HASH,
        "ops_count": len(g["interior_ops"]),
        "ops_verbatim": True,
    }
    assert r["mep"] == {"review_id": "rv-mep", "content_hash": HASH, "ops_count": len(plan["ops"])}
    assert r["counts"]["ops"] == len(g["interior_ops"]) + len(plan["ops"]) + 1
    assert r["counts"]["run_interference_check"] == 1
    assert r["replan_deltas"] == [] and r["dropped"] == [] and r["blocked_reason"] is None
    report = r["clash_report"]
    assert report["status"] == "clean" and report["open_clashes"] == []
    assert report["budget"] == {"limit": MERGE_BUDGET, "used": 0, "remaining": MERGE_BUDGET}
    assert report["phase_a"] == {"rounds": []} and report["phase_b"] == {"replans": []}
    assert set(report["prisms"]) == {"furniture", "pipe", "device", "conduit"}
    assert set(r["svgs"]) == {"commit1", "merged"}
    assert all(svg.startswith("<svg") for svg in r["svgs"].values())
    assert r["svgs"]["commit1"] != r["svgs"]["merged"]
    validate_ops(r["ops"][:-1])
    assert validate_layout(r["layout"]) == []
    assert r["layout"]["meta"]["levels"]["slab_to_slab"] == 3000.0


def test_merge_is_deterministic():
    assert json.dumps(run(), sort_keys=True) == json.dumps(run(), sort_keys=True)


# ---- Phase A ---------------------------------------------------------------------


def test_phase_a_slides_a_device_off_the_stack_and_leaves_no_clash():
    plan = forced_onto_stack("E-013")  # bedroom receptacle on the bath wet wall W-004
    s = stack(plan)
    before = phase_a(build_prisms(plan["layout"], plan["ops"], {}))
    assert [(c.a_id, c.b_id, c.a_cls, c.b_cls, c.a_priority, c.b_priority) for c in before] == [
        ("P-001", "E-013", "pipe", "device", 1, 4)
    ]
    assert before[0].overlap_area_mm2 > 0 and before[0].z_overlap_mm == 120.0
    r = run(plan)
    assert r["status"] == "clean" and r["iterations_used"] == 1
    shifts = [a for a in r["actions"] if a["action"] == "shift_device"]
    [act] = shifts
    assert act["trigger"] == "phase_a"
    assert act["lower"] == "E-013" and act["higher"] == "P-001" and act["changed"] is True
    assert act["params"]["before"]["offset"] == s["offset"]
    k = act["params"]["k"]
    assert 1 <= k <= 8
    assert abs(abs(act["params"]["after"]["offset"] - s["offset"]) - 150.0 * k) < 1e-6
    # the new slot clears the stack's ±300 E-4 exclusion square: the device stays routable
    assert abs(act["params"]["after"]["offset"] - s["offset"]) > 300.0
    assert r["dropped"] == []
    assert act["params"]["after"]["face"] in ("left", "right")
    [round_] = r["clash_report"]["phase_a"]["rounds"]
    assert round_["clashes"][0]["a_id"] == "P-001" and round_["clashes"][0]["b_id"] == "E-013"
    branch_fixtures = {b["id"]: b["fixture_ids"] for b in plan["branches"]}
    assert phase_a(build_prisms(r["layout"], mep_ops_of(r), branch_fixtures)) == []
    moved = next(op for op in r["ops"] if op["args"].get("id") == "E-013")
    assert moved["args"]["offset"] == act["params"]["after"]["offset"]
    # conduits are derived state: the drop for E-013 lands at its new foot
    assert r["counts"]["place_device"] == 45 and r["interior"]["ops_verbatim"] is True


def test_furniture_relegalizes_around_structure_and_the_op_follows():
    plan = golden_plan()
    bed = item_by_id(plan["layout"], "F-001")
    r = run(with_column(bed["center"], [300.0, 300.0]))
    assert r["status"] == "clean" and r["iterations_used"] == 1
    [act] = r["actions"]
    assert act["action"] == "relegalize_furniture" and act["lower"] == "F-001"
    assert act["higher"] == "C-001" and act["higher_priority"] == 0 and act["lower_priority"] == 5
    assert act["params"]["before"] == {"center": bed["center"], "rotation_deg": bed["rotation_deg"]}
    after = act["params"]["after"]
    assert after != act["params"]["before"] and act["params"]["obstacle_buffer_mm"] == 50.0
    moved = item_by_id(r["layout"], "F-001")
    assert moved["center"] == after["center"] and moved["rotation_deg"] == after["rotation_deg"]
    op = next(op for op in r["ops"] if op["args"].get("id") == "F-001")
    assert op["args"]["center"] == [round(c, 1) for c in after["center"]]
    assert op["args"]["rotation_deg"] == after["rotation_deg"]
    assert r["interior"]["ops_verbatim"] is False and r["dropped"] == []
    assert [d["id"] for d in r["replan_deltas"]] == ["F-001"]
    # untouched interior ops are byte-identical to the approved branch
    approved = {op["args"]["id"]: op for op in golden_chain()["interior_ops"]}
    for op in r["ops"]:
        if op["op"] == "place_family" and op["args"]["id"] != "F-001":
            assert op == approved[op["args"]["id"]]
    # preplaced seam: the moved bed clears the column AND every other item
    column = box(
        bed["center"][0] - 150,
        bed["center"][1] - 150,
        bed["center"][0] + 150,
        bed["center"][1] + 150,
    )
    rect = furniture_rect(moved)
    assert rect.intersection(column).area == 0
    for other in all_items(r["layout"]):
        if other["id"] != "F-001":
            assert rect.intersection(furniture_rect(other)).area == 0
    assert validate_layout(r["layout"]) == []


def test_structure_on_the_stack_relocates_it_off_the_wall():
    plan = golden_plan()
    r = run(with_column(stack_xy(plan), [100.0, 100.0]))  # inside the 152 mm wet wall
    assert r["status"] == "clean" and r["iterations_used"] >= 1
    relocate = next(a for a in r["actions"] if a["action"] == "relocate_stack")
    assert relocate["lower"] == "P-001" and relocate["higher"] == "C-001"
    assert relocate["params"] == {"banned_walls": ["W-004"], "stack": "P-001"}
    pipes = [op for op in r["ops"] if op["op"] == "create_pipe"]
    verticals = [op for op in pipes if op["args"]["path"][0][:2] == op["args"]["path"][1][:2]]
    wall4 = next(w for w in plan["layout"]["walls"] if w["id"] == "W-004")
    line = LineString([wall4["start"], wall4["end"]])
    for op in verticals:
        assert line.distance(Point(op["args"]["path"][0][:2])) > 76.0  # off the banned wall
    # every sanitary fixture is still served by some branch
    sanitary = {i["id"] for i in all_items(plan["layout"]) if "sanitary" in i.get("hookups", [])}
    served = _served_fixtures(r)
    assert served == sanitary
    assert r["interior"]["ops_verbatim"] is True
    # a device the relocated stack's new exclusion square isolates is DROPPED and reported,
    # never left without a home run
    for dropped in r["dropped"]:
        assert dropped.startswith("E-")
        assert dropped not in ids(r["ops"], "place_device")
        assert any(d["id"] == dropped and d["kind"] == "device" for d in r["replan_deltas"])
        assert any(a["action"] == "drop" and a["lower"] == dropped for a in r["actions"])


def _served_fixtures(result) -> set[str]:
    # branch legs end under a fixture: recover service from the leg foot ∈ fixture rect
    fixtures = [i for i in all_items(result["layout"]) if "sanitary" in i.get("hookups", [])]
    served: set[str] = set()
    for op in result["ops"]:
        if op["op"] != "create_pipe":
            continue
        for point in op["args"]["path"]:
            for fx in fixtures:
                if furniture_rect(fx).buffer(1.0).contains(Point(point[:2])):
                    served.add(fx["id"])
    return served


# ---- Phase B ---------------------------------------------------------------------


def test_injected_clash_resolves_within_budget_then_exhausts_it():
    prior: list[dict] = []
    used = 0
    offsets = []
    for iteration in range(1, MERGE_BUDGET + 2):
        r = run(used=used, iteration=iteration, prior=prior, pairs=[pair("P-001", "E-001")])
        if iteration <= MERGE_BUDGET:
            assert r["status"] == "clean" and r["iterations_used"] == used + 1
            [act] = r["actions"]
            assert act["trigger"] == "phase_b" and act["action"] == "shift_device"
            assert act["lower"] == "E-001" and act["params"]["away_from"] == "P-001"
            offsets.append(act["params"]["after"]["offset"])
            assert r["counts"]["ops"] == len(run()["ops"])
            [replan] = r["clash_report"]["phase_b"]["replans"]
            assert replan["iteration"] == iteration and replan["pairs"] == [pair("P-001", "E-001")]
            prior = prior + r["actions"]
            used = r["iterations_used"]
        else:
            assert r["status"] == "budget_exhausted" and r["iterations_used"] == MERGE_BUDGET
            assert r["ops"] == [] and r["svgs"] == {} and r["actions"] == []
            assert r["clash_report"]["budget"]["remaining"] == 0
    assert offsets == [1762.5, 1612.5, 1462.5]  # 1912.5 − 150·k, k = 1 each round


def test_replay_of_prior_actions_is_stateless_and_identical():
    first = run(pairs=[pair("P-001", "E-001")])
    replayed = run(used=first["iterations_used"], iteration=2, prior=first["actions"])
    assert replayed["status"] == "clean" and replayed["actions"] == []
    assert replayed["iterations_used"] == first["iterations_used"] == 1
    assert json.dumps(replayed["ops"], sort_keys=True) == json.dumps(first["ops"], sort_keys=True)
    assert replayed["layout"] == first["layout"]


def test_shared_budget_counts_phase_b_and_phase_a_rounds_together():
    plan = golden_plan()
    bed = item_by_id(plan["layout"], "F-001")
    column = with_column(bed["center"], [300.0, 300.0])  # a Phase A clash routing cannot touch
    r = run(column, pairs=[pair("P-001", "E-001")])
    assert r["status"] == "clean" and r["iterations_used"] == 2
    assert [(a["trigger"], a["action"], a["lower"]) for a in r["actions"]] == [
        ("phase_b", "shift_device", "E-001"),
        ("phase_a", "relegalize_furniture", "F-001"),
    ]
    # two rounds already spent: Phase B takes the last one, Phase A finds the overlap
    # and may not start another round → REVIEW with the open clash listed
    r = run(column, used=MERGE_BUDGET - 1, iteration=3, pairs=[pair("P-001", "E-001")])
    assert r["status"] == "budget_exhausted" and r["iterations_used"] == MERGE_BUDGET
    assert [a["lower"] for a in r["actions"]] == ["E-001"]
    assert [(c["a_id"], c["b_id"]) for c in r["clash_report"]["open_clashes"]] == [
        ("C-001", "F-001")
    ]
    assert r["ops"] == []


def test_structure_reported_by_the_executor_relocates_the_stack():
    r = run(pairs=[pair("revit:4711", "P-001")])
    assert r["status"] == "clean" and r["iterations_used"] == 1
    [act] = [a for a in r["actions"] if a["action"] == "relocate_stack"]
    assert act["higher"] == "revit:4711"
    assert act["higher_priority"] == 0 and act["params"]["banned_walls"] == ["W-004"]
    # a branch segment names its stack through the recorded segment → stack map
    r2 = run(pairs=[pair("revit:4711", "P-004")])
    assert r2["actions"][0]["action"] == "relocate_stack"
    assert r2["actions"][0]["params"]["stack"] == "P-001"


def test_progress_guarantee_escalates_then_drops_and_the_drop_sticks():
    plan = golden_plan()
    far = ids(plan["ops"], "create_conduit")[-1]  # a trunk nowhere near the stack
    r = run(pairs=[pair("P-001", far)])
    assert r["status"] == "clean" and r["iterations_used"] == 1
    act = r["actions"][0]  # the trunk drop; the orphaned devices' drops follow it
    assert act["action"] == "drop" and act["lower"] == far and act["changed"] is True
    assert all(a["action"] == "drop" and a["lower"].startswith("E-") for a in r["actions"][1:])
    assert act["params"]["reason"] == "no progress after escalation"
    far_path = next(op["args"]["path"] for op in plan["ops"] if op["args"].get("id") == far)
    assert act["params"]["path"] == far_path  # the GEOMETRY is what stays dropped
    assert r["dropped"][0] == far and far not in ids(r["ops"], "create_conduit")
    assert far_path not in [op["args"]["path"] for op in r["ops"] if op["op"] == "create_conduit"]
    # the trunk was the ONLY path for some devices: with its geometry forbidden they lose
    # their home run and are dropped + reported — never left silently without a conduit
    orphans = r["dropped"][1:]
    assert orphans and all(d.startswith("E-") for d in orphans)
    for d in orphans:
        assert d not in ids(r["ops"], "place_device")
        assert any(x["id"] == d and x["kind"] == "device" for x in r["replan_deltas"])
    _every_device_has_its_drop(r)
    # a later round re-derives the raceway tree; the dropped GEOMETRY stays out even when
    # trunk ids move (the replay re-forbids it from the recorded path)
    again = run(used=1, iteration=2, prior=r["actions"], pairs=[pair("P-001", "E-001")])
    assert again["status"] == "clean" and far not in ids(again["ops"], "create_conduit")
    assert far_path not in [
        op["args"]["path"] for op in again["ops"] if op["op"] == "create_conduit"
    ]
    assert again["dropped"] == r["dropped"]
    _every_device_has_its_drop(again)


def _every_device_has_its_drop(result) -> None:
    """Q-n <-> E-n: every remaining device owns exactly one vertical drop at its foot."""
    conduit_ids = set(ids(result["ops"], "create_conduit"))
    for device in ids(result["ops"], "place_device"):
        assert f"Q-{device[2:]}" in conduit_ids, device


def test_same_priority_pair_is_blocked_not_guessed():
    r = run(pairs=[pair("F-001", "F-002")])
    assert r["status"] == "blocked" and r["ops"] == [] and r["iterations_used"] == 1
    assert r["blocked_reason"] == "F-001~F-002: same clash priority 5"
    assert r["actions"][0]["action"] == "blocked" and r["actions"][0]["changed"] is False


def test_unknown_pair_is_a_contract_error():
    with pytest.raises(MergeError) as err:
        run(pairs=[pair("X-999", "Y-999")])
    assert err.value.code == "clash_pair_unknown"
    with pytest.raises(MergeError) as err:
        run(pairs=[pair("E-001", "Y-999")])
    assert err.value.code == "clash_pair_unknown"
    with pytest.raises(MergeError) as err:
        run(pairs=[pair("revit:1", "revit:2")])
    assert err.value.code == "clash_pair_unknown"


def test_ids_never_renumber_across_replans():
    plan = golden_plan()
    bed = item_by_id(plan["layout"], "F-001")
    scenarios = [
        run(forced_onto_stack("E-013")),
        run(with_column(bed["center"], [300.0, 300.0])),
        run(pairs=[pair("P-001", "E-001")]),
        run(with_column(stack_xy(plan), [100.0, 100.0])),
    ]
    for r in scenarios:
        assert r["status"] == "clean"
        # devices/furniture keep their ids (a dropped device is listed, never renumbered)
        assert ids(r["ops"], "place_device") == [
            i for i in ids(plan["ops"], "place_device") if i not in r["dropped"]
        ]
        assert {i["id"] for i in all_items(r["layout"])} == {
            i["id"] for i in all_items(plan["layout"])
        } - set(r["dropped"])
        assert ids(r["ops"], "place_family") == ids(golden_chain()["interior_ops"], "place_family")
        replanned = any(a["action"] in ("relocate_stack", "replan_plumbing") for a in r["actions"])
        if replanned:  # pipes are derived state after P-1..P-4 re-ran (ids may renumber)
            assert set(ids(r["ops"], "create_pipe")) <= {f"P-{i:03d}" for i in range(1, 40)}
        else:
            assert ids(r["ops"], "create_pipe") == ids(plan["ops"], "create_pipe")
        conduits = ids(r["ops"], "create_conduit")
        assert len(set(conduits)) == r["counts"]["create_conduit"]
        # drop Q-n <-> device E-n, always
        for op in r["ops"]:
            if op["op"] == "create_conduit" and len(op["args"]["path"]) == 2:
                a, b = op["args"]["path"]
                if a[:2] == b[:2]:  # a vertical drop
                    n = op["args"]["id"][2:]
                    assert f"E-{n}" in ids(r["ops"], "place_device")


# ---- ONE clash law ---------------------------------------------------------------


def _sim_pairs(layout, mep_ops) -> set[frozenset[str]]:
    from revit_sim.clash import element_boxes, find_clashes
    from revit_sim.model import Catalogs

    from layout_compiler.replay import sim_model_from_layout

    g, catalogs = golden_chain(), Catalogs.load()
    model = sim_model_from_layout(g["commit0"])
    for op in [*g["commit1_ops"], *g["interior_ops"], *mep_ops]:
        model.apply(op["op"], op["args"], catalogs)
    return {
        frozenset(p)
        for p in find_clashes(element_boxes(model, catalogs), None, catalogs.clash_prisms)
    }


@pytest.mark.parametrize("device_id", ["E-009", "E-013", "E-031", "E-035", "E-043"])
def test_phase_a_clashes_are_a_subset_of_the_sim_law(device_id):
    plan = golden_plan()
    index = 1 if device_id == "E-043" else 0
    forced = forced_onto_stack(device_id, index)
    oriented = {
        frozenset((c.a_id, c.b_id)) for c in phase_a(build_prisms(forced["layout"], forced["ops"]))
    }
    assert oriented, "the forced plan must clash in Phase A"
    aabb = _sim_pairs(forced["layout"], forced["ops"])
    assert oriented <= aabb
    assert (
        _sim_pairs(plan["layout"], plan["ops"])
        == set()
        == {frozenset((c.a_id, c.b_id)) for c in phase_a(build_prisms(plan["layout"], plan["ops"]))}
    )


def test_exemption_table_is_shared_with_the_sim():
    from revit_sim.clash import Box
    from revit_sim.clash import exempt as sim_exempt
    from revit_sim.model import Catalogs

    prisms = Catalogs.load().clash_prisms
    square = box(0, 0, 100, 100)
    classes = [
        ("pipe", "sanitary", frozenset({"F-001"})),
        ("pipe", "sanitary", frozenset()),
        ("pipe", "vent", frozenset()),
        ("conduit", None, frozenset()),
        ("device", None, frozenset()),
        ("furniture", None, frozenset()),
    ]
    for a_cls, a_sys, a_serves in classes:
        for b_cls, b_sys, b_serves in classes:
            a = Prism(
                "F-001" if a_cls == "furniture" else "A", a_cls, 0, a_sys, square, 0, 1, a_serves
            )
            b = Prism(
                "F-001" if b_cls == "furniture" else "B", b_cls, 0, b_sys, square, 0, 1, b_serves
            )
            sim = sim_exempt(
                Box(a.element_id, a_cls, a_sys, 0, 0, 1, 1, 0, 1),
                Box(b.element_id, b_cls, b_sys, 0, 0, 1, 1, 0, 1),
                prisms,
            )
            ours = phase_a_exempt(a, b)
            if {a_cls, b_cls} == {"pipe", "furniture"}:
                assert not sim  # unresolvable in the sim → strict
                pipe = a if a_cls == "pipe" else b
                assert ours is ("F-001" in pipe.serves)  # resolvable here
            else:
                assert ours == sim, (a_cls, a_sys, b_cls, b_sys)


# ---- hard errors -----------------------------------------------------------------


def test_validator_oracle_guards_the_clean_path(monkeypatch):
    monkeypatch.setattr(gate_mod, "validate_layout", lambda layout: ["rooms.R-001: boom"])
    with pytest.raises(MergeError) as err:
        run()
    assert err.value.code == "merge_internal" and "boom" in err.value.message


def test_blocking_plan_and_invalid_interior_are_refused():
    plan = copy.deepcopy(golden_plan())
    plan["blocking"] = ["levels_missing"]
    with pytest.raises(MergeError) as err:
        run(plan)
    assert err.value.code == "merge_internal"
    with pytest.raises(MergeError) as err:
        run(interior_layout={"meta": {}})
    assert err.value.code == "interior_layout_invalid"


def test_timeout_is_a_hard_error(monkeypatch):
    monkeypatch.setattr(gate_mod, "MERGE_TIME_LIMIT_S", 0.0)
    with pytest.raises(MergeError) as err:
        run()
    assert err.value.code == "merge_timeout"


def test_merge_rules_are_clock_free_except_the_gate():
    forbidden = {"random", "time", "datetime", "os", "secrets", "uuid"}
    for path in sorted(MERGE_SRC.glob("*.py")):
        if path.name == "gate.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            assert not (set(names) & forbidden), f"{path.name} imports {names}"
    tree = ast.parse((MERGE_SRC / "gate.py").read_text())
    calls = {
        f"time.{n.func.attr}"
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "time"
    }
    assert calls == {"time.monotonic"}


def test_dropped_conduit_geometry_stays_out_when_trunk_ids_shift(monkeypatch):
    """Ids are transient for trunks: after a device drop every later trunk renumbers.
    The dropped trunk's GEOMETRY must stay out and no unrelated conduit may vanish."""
    from layout_compiler.merge import replan as replan_mod

    plan = golden_plan()
    trunk = ids(plan["ops"], "create_conduit")[-1]
    trunk_path = next(op["args"]["path"] for op in plan["ops"] if op["args"].get("id") == trunk)
    first = run(pairs=[pair("P-001", trunk)])
    assert first["dropped"][0] == trunk  # plus the devices that only reached the panel via it
    # now force a device drop: no slot is ever legal -> escalation -> drop E-005
    monkeypatch.setattr(replan_mod, "legal_on_runs", lambda runs, trial: False)
    second = run(used=1, iteration=2, prior=first["actions"], pairs=[pair("P-001", "E-005")])
    assert second["status"] == "clean"
    assert second["dropped"][0] == trunk and second["dropped"][-1] == "E-005"
    assert set(second["dropped"]) == set(first["dropped"]) | {"E-005"}
    paths = [op["args"]["path"] for op in second["ops"] if op["op"] == "create_conduit"]
    assert trunk_path not in paths
    gone = set(second["dropped"])
    before = {
        json.dumps(op["args"]["path"])
        for op in plan["ops"]
        if op["op"] == "create_conduit"
        and op["args"]["id"] != trunk
        and f"E-{op['args']['id'][2:]}" not in gone
    }
    after = {json.dumps(p) for p in paths}
    # every surviving device's drop is byte-identical; trunks re-route around the geometry
    drops_before = {p for p in before if json.loads(p)[0][:2] == json.loads(p)[1][:2]}
    assert drops_before <= after
    assert "E-005" not in ids(second["ops"], "place_device")
    assert "Q-005" not in ids(second["ops"], "create_conduit")
    _every_device_has_its_drop(second)


def test_device_escalation_reaches_the_second_band_before_dropping(monkeypatch):
    """PIN-26: k = 1..4 fails -> escalate to k = 5..8 -> only then drop."""
    from layout_compiler.merge import replan as replan_mod

    real = replan_mod.legal_on_runs
    # legal only ≥ 750 mm away from the original E-001 offset (1912.5)
    monkeypatch.setattr(
        replan_mod,
        "legal_on_runs",
        lambda runs, trial: abs(trial - 1912.5) >= 750 and real(runs, trial),
    )
    r = run(pairs=[pair("P-001", "E-001")])
    [act] = [a for a in r["actions"] if a["lower"] == "E-001"]
    assert act["action"] == "shift_device" and act["params"]["k"] >= 5
    assert "E-001" in ids(r["ops"], "place_device")
    # nothing legal anywhere -> drop, recorded once
    monkeypatch.setattr(replan_mod, "legal_on_runs", lambda runs, trial: False)
    r2 = run(pairs=[pair("P-001", "E-001")])
    [act2] = [a for a in r2["actions"] if a["lower"] == "E-001"]
    assert act2["action"] == "drop" and r2["dropped"] == ["E-001"]


def test_structure_pairs_are_existing_conditions_not_clashes():
    plan = with_column(stack_xy(golden_plan()), [100.0, 100.0])
    plan["layout"]["columns"].append(
        {
            "id": "C-002",
            "center": plan["layout"]["columns"][0]["center"],
            "footprint": [100.0, 100.0],
        }
    )
    prisms = build_prisms(plan["layout"], plan["ops"], {})
    pairs = {(c.a_id, c.b_id) for c in phase_a(prisms)}
    assert ("C-001", "C-002") not in pairs and ("C-002", "C-001") not in pairs
    assert ("C-001", "P-001") in pairs and ("C-002", "P-001") in pairs
    r = run(plan)
    assert r["status"] == "clean"


def test_moving_a_plumbing_fixture_records_a_replan_plumbing_action():
    """A column under the lav: the fixture re-legalizes, so P-1..P-4 re-run and the
    pipes are derived state — the RECORDED action is what tells the gateway verifier."""
    plan = golden_plan()
    lav = item_by_id(plan["layout"], "F-007")
    r = run(with_column(lav["center"], [200.0, 200.0]))
    assert r["status"] == "clean"
    kinds = [a["action"] for a in r["actions"]]
    assert "relegalize_furniture" in kinds and "replan_plumbing" in kinds
    replan = next(a for a in r["actions"] if a["action"] == "replan_plumbing")
    assert replan["params"]["fixture_id"] == "F-007"
    assert set(replan["params"]["pipe_ids"]) == set(ids(r["ops"], "create_pipe"))
    # the moved fixture is still served: its new position has a drain leg
    served = _served_fixtures(r)
    assert "F-007" in served
    assert validate_layout(r["layout"]) == []
