"""revit_sim.clash — the sim's half of the ONE clash law: 2.5D boxes from
catalogs/clash_prisms.json, strict overlap on x/y/z, shared exemption pairs,
created-set scope, deterministic first pair, and the executor's envelope wiring."""

from signing import make_body, sign_envelope, wall_op

from revit_sim.clash import Box, element_boxes, exempt, family_height_mm, find_clashes, overlaps
from revit_sim.model import Catalogs, SimModel

CATALOGS = Catalogs.load()
PRISMS = CATALOGS.clash_prisms
PIPE_TYPE = "CHPT_Pipe_PVC_DWV_PLACEHOLDER"


def wall(model: SimModel, i: int = 1, y: float = 0.0) -> None:
    model.apply(
        "create_wall",
        {
            "id": f"W-{i:03d}",
            "start": [0, y],
            "end": [4000, y],
            "revit_type": "CHPT_Partition_92mm_PLACEHOLDER",
            "height": 2700,
            "phase": "new",
        },
        CATALOGS,
    )


def family(model: SimModel, fid: str, center: list[float], footprint=(600.0, 600.0), rot=0.0):
    model.apply(
        "place_family",
        {
            "id": fid,
            "revit_family": "CHPT_Nightstand_PLACEHOLDER",
            "revit_type": "Nightstand_450x450_PLACEHOLDER",
            "center": center,
            "rotation_deg": rot,
            "footprint": list(footprint),
            "level": "Level 1",
        },
        CATALOGS,
    )


def device(model: SimModel, did: str, offset: float, face: str = "left", kind="receptacle"):
    model.apply(
        "place_device",
        {
            "id": did,
            "kind": kind,
            "host_wall_id": "W-001",
            "offset": offset,
            "height_afl": 380,
            "face": face,
        },
        CATALOGS,
    )


def pipe(model: SimModel, pid: str, path, diameter=76.0, system="sanitary"):
    model.apply(
        "create_pipe",
        {
            "id": pid,
            "system": system,
            "pipe_type": PIPE_TYPE,
            "level": "Level 1",
            "path": path,
            "diameter": diameter,
        },
        CATALOGS,
    )


def conduit(model: SimModel, cid: str, path, diameter=21.0):
    model.apply(
        "create_conduit",
        {"id": cid, "level": "Level 1", "path": path, "diameter": diameter},
        CATALOGS,
    )


def test_family_height_is_the_catalog_kind_height():
    nightstand = ("CHPT_Nightstand_PLACEHOLDER", "Nightstand_450x450_PLACEHOLDER")
    wardrobe = ("CHPT_Wardrobe_PLACEHOLDER", "Wardrobe_1000x600_PLACEHOLDER")
    assert family_height_mm(CATALOGS, *nightstand) == 750.0
    assert family_height_mm(CATALOGS, *wardrobe) == 2100.0
    assert family_height_mm(CATALOGS, "Unknown", "Unknown") == 900.0  # default


def test_boxes_per_element_kind():
    model = SimModel()
    wall(model)
    family(model, "F-001", [1000.0, 1000.0], footprint=(2000.0, 600.0), rot=90.0)
    device(model, "E-001", 2000.0, face="left")
    pipe(model, "P-001", [[3000, 0, -300], [3000, 0, 2700]])
    conduit(model, "Q-001", [[500, 46, 380], [500, 46, 2600]])
    boxes = {b.element_id: b for b in element_boxes(model, CATALOGS)}
    assert set(boxes) == {"F-001", "E-001", "P-001", "Q-001"}  # walls are not clash elements
    fam = boxes["F-001"]  # rotated 90: 600 x 2000 AABB, z 0..750
    assert (round(fam.x0), round(fam.y0), round(fam.x1), round(fam.y1)) == (700, 0, 1300, 2000)
    assert (fam.z0, fam.z1) == (0.0, 750.0)
    dev = boxes["E-001"]  # along +/-50 at the centerline foot, across +/-46, z 320..440
    assert (dev.x0, dev.y0, dev.x1, dev.y1) == (1950.0, -46.0, 2050.0, 46.0)
    assert (dev.z0, dev.z1) == (320.0, 440.0)
    stack = boxes["P-001"]  # radius 38 around the stack, z spans the path +/- radius
    assert (stack.x0, stack.x1, stack.z0, stack.z1) == (2962.0, 3038.0, -338.0, 2738.0)
    assert stack.system == "sanitary" and stack.cls == "pipe"
    assert boxes["Q-001"].cls == "conduit" and boxes["Q-001"].system is None


def test_exemptions_follow_the_shared_table():
    def box(cls, system=None):
        return Box("x", cls, system, 0, 0, 1, 1, 0, 1)

    assert exempt(box("pipe", "sanitary"), box("pipe", "sanitary"), PRISMS)
    assert not exempt(box("pipe", "sanitary"), box("pipe", "supply_c"), PRISMS)
    assert exempt(box("conduit"), box("conduit"), PRISMS)
    assert exempt(box("device"), box("device"), PRISMS)
    assert exempt(box("device"), box("conduit"), PRISMS)
    assert exempt(box("conduit"), box("device"), PRISMS)
    assert exempt(box("furniture"), box("device"), PRISMS)
    assert exempt(box("furniture"), box("conduit"), PRISMS)
    # pipe_serves_fixture is unresolvable in the sim -> strict
    assert not exempt(box("pipe", "sanitary"), box("furniture"), PRISMS)
    assert not exempt(box("pipe", "sanitary"), box("device"), PRISMS)
    assert not exempt(box("pipe", "sanitary"), box("conduit"), PRISMS)


def test_overlap_is_strict_on_every_axis():
    a = Box("a", "pipe", "sanitary", 0, 0, 100, 100, 0, 100)
    assert not overlaps(a, Box("b", "conduit", None, 100, 0, 200, 100, 0, 100))  # touching x
    assert not overlaps(a, Box("b", "conduit", None, 0, 0, 100, 100, 100, 200))  # touching z
    assert overlaps(a, Box("b", "conduit", None, 99, 99, 200, 200, 99, 200))


def test_legacy_family_pairs_and_created_scope():
    model = SimModel()
    family(model, "F-001", [1000.0, 1000.0])
    family(model, "F-002", [1500.0, 1000.0])  # overlaps F-001 by 100mm
    family(model, "F-003", [3000.0, 1000.0])
    boxes = element_boxes(model, CATALOGS)
    assert find_clashes(boxes, None, PRISMS) == [("F-001", "F-002")]  # all pairs, sorted
    # created-set scope: a pre-existing overlapping pair is not this envelope's problem
    assert find_clashes(boxes, ["F-003"], PRISMS) == []
    # created element first, then the other
    assert find_clashes(boxes, ["F-002"], PRISMS) == [("F-002", "F-001")]


def test_below_floor_branch_never_clashes_with_furniture_but_a_stack_through_a_device_does():
    model = SimModel()
    wall(model)
    family(model, "F-001", [1000.0, 400.0], footprint=(600.0, 600.0))
    pipe(model, "P-001", [[1000, 400, -188.0], [1000, 0, -162.5]], diameter=38.0)  # under the slab
    boxes = element_boxes(model, CATALOGS)
    assert find_clashes(boxes, None, PRISMS) == []
    device(model, "E-001", 2000.0)
    pipe(model, "P-002", [[2000, 0, -300], [2000, 0, 2700]])  # stack through the device box
    assert find_clashes(element_boxes(model, CATALOGS), ["P-002"], PRISMS) == [("P-002", "E-001")]


def test_envelope_wiring_scopes_to_created_and_resets_after_commit(make_executor):
    ex = make_executor()
    # envelope 1: two overlapping families WITHOUT a check -> commits (legacy behaviour)
    fam = lambda fid, x: {  # noqa: E731
        "op": "place_family",
        "args": {
            "id": fid,
            "revit_family": "CHPT_Nightstand_PLACEHOLDER",
            "revit_type": "Nightstand_450x450_PLACEHOLDER",
            "center": [x, 1000.0],
            "rotation_deg": 0.0,
            "footprint": [600.0, 600.0],
            "level": "Level 1",
        },
    }
    check = {"op": "run_interference_check", "args": {"scope": "last_commit"}}
    first = ex.handle_envelope(
        sign_envelope(make_body(1, [fam("F-001", 1000.0), fam("F-002", 1500.0)]))
    )
    assert first[-1]["status"] == "committed"
    assert ex.model.envelope_created is None
    # envelope 2: a far-away family + check -> clean (the old pair is outside the created set)
    second = ex.handle_envelope(sign_envelope(make_body(2, [fam("F-003", 3000.0), check])))
    assert second[-1]["status"] == "committed"
    assert ex.model.envelope_created is None
    # envelope 3: a family overlapping F-003 + check -> interference + clash_delta, nothing kept
    third = ex.handle_envelope(sign_envelope(make_body(3, [fam("F-004", 3300.0), check])))
    assert [m["type"] for m in third] == ["ack", "commit_result", "clash_delta"]
    assert third[1]["status"] == "rolled_back"
    assert third[1]["errors"][0] == {
        "op_index": 1,
        "code": "interference",
        "message": "F-004~F-003",
    }
    assert third[2]["pairs"] == [{"a_id": "F-004", "b_id": "F-003", "kind": "hard_interference"}]
    assert "F-004" not in ex.model.families


def test_wall_op_helper_is_unused_guard():
    assert wall_op(1)["op"] == "create_wall"
