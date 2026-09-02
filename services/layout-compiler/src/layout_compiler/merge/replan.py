"""Lower-priority re-plans (docs/PHASE6_DESIGN.md §4.4, PIN-26/27): the element with
the higher priority NUMBER moves — furniture re-legalizes through the Phase 5 placer
(preplaced + obstacle seams), devices slide ±150·k away from the clash, conduits
re-route with the clash as a forbidden obstacle, a stack relocates off its wall.
Every action is recorded with before/after and is REPLAYABLE without re-searching
(the merge endpoint is stateless); the progress guarantee escalates once and then
drops the element (never an unchanged element after an action). Ids of furniture,
devices and pipes are never re-assigned; conduit trunks are re-derived from the
raceway tree (drops keep their device pairing)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from shapely import wkt
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from layout_compiler.geometry import pt_on_wall
from layout_compiler.interior import legalize_furniture
from layout_compiler.mep.constants import DEVICE_B2B_MM, DEVICE_SHIFT_MM
from layout_compiler.mep.electrical import Device, room_face
from layout_compiler.mep.inputs import MepInputs, offset_of
from layout_compiler.mep.ops import conduit_ops, pipe_ops
from layout_compiler.mep.plumbing import plan_plumbing
from layout_compiler.mep.routing import route_home_runs
from layout_compiler.mep.runs import legal_on_runs, wall_runs
from layout_compiler.merge.prisms import Prism, build_prisms
from layout_compiler.validator import validate_layout

OBSTACLE_BUFFER_MM = 50.0
OBSTACLE_BUFFER_ESCALATED_MM = 300.0


class MergeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class MergeState:
    layout: dict[str, Any]  # furnished layout, meta stamped; furniture mutates
    interior_ops: list[dict[str, Any]]
    mep_ops: list[dict[str, Any]]
    branch_fixtures: dict[str, list[str]]
    devices_meta: dict[str, dict[str, Any]]  # id -> {room_id, rule, ...} from the MepPlan
    stacks_meta: list[dict[str, Any]]  # [{id, wall_id, offset}]
    inputs: MepInputs
    segment_stack: dict[str, str] = field(default_factory=dict)  # branch id -> stack id
    refresh_inputs: Callable[[dict[str, Any]], MepInputs] | None = None
    banned_walls: set[str] = field(default_factory=set)
    obstacles: list[BaseGeometry] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    interior_verbatim: bool = True
    replan_deltas: list[dict[str, Any]] = field(default_factory=list)
    blocked: str | None = None

    # ---- lookups ------------------------------------------------------------
    def op_by_id(self, element_id: str) -> dict[str, Any] | None:
        for op in [*self.interior_ops, *self.mep_ops]:
            if op["args"].get("id") == element_id:
                return op
        return None

    def furniture_items(self) -> list[dict[str, Any]]:
        return [
            {**item, "room_id": entry["room_id"]}
            for entry in self.layout.get("furniture", [])
            for item in entry["items"]
        ]

    def prisms(self) -> list[Prism]:
        return build_prisms(self.layout, self.mep_ops, self.branch_fixtures)

    def devices(self) -> list[Device]:
        out: list[Device] = []
        for op in self.mep_ops:
            if op["op"] != "place_device":
                continue
            a = op["args"]
            meta = self.devices_meta.get(a["id"], {})
            out.append(
                Device(
                    kind=a["kind"],
                    rule=meta.get("rule", "E-1"),
                    room_id=meta.get("room_id", ""),
                    host_wall_id=a["host_wall_id"],
                    offset=float(a["offset"]),
                    height_afl=float(a["height_afl"]),
                    face=a["face"],
                    id=a["id"],
                )
            )
        return out

    def zones(self) -> list[tuple[str, float]]:
        return [(s["wall_id"], float(s["offset"])) for s in self.stacks_meta]

    # ---- rebuilds -----------------------------------------------------------
    def rerun_routing(self, deadline_check=None) -> None:
        """Conduits are derived state: drops keep their device pairing (Q-n follows
        device order), trunk chains follow the raceway tree."""
        pipes = [op for op in self.mep_ops if op["op"] == "create_pipe"]
        devices = [op for op in self.mep_ops if op["op"] == "place_device"]
        result = route_home_runs(
            self.inputs, self.devices(), self.zones(), deadline_check, list(self.obstacles)
        )
        conduits = [
            op
            for op in conduit_ops(result.drops, result.trunks, self.inputs)
            if op["args"]["id"] not in self.dropped
        ]
        self.mep_ops = pipes + devices + conduits

    def rerun_plumbing(self, deadline_check=None) -> bool:
        """Relocate: re-run P-1..P-4 with the banned walls; False when no candidate."""
        result = plan_plumbing(self.inputs, deadline_check, banned_walls=sorted(self.banned_walls))
        if any(i.code == "no_wet_wall_candidate" for i in result.items) or not result.stacks:
            return False
        others = [op for op in self.mep_ops if op["op"] != "create_pipe"]
        self.mep_ops = pipe_ops(result.stacks, result.segments, self.inputs) + others
        self.branch_fixtures = {s.id: list(s.fixture_ids) for s in result.segments}
        self.segment_stack = {s.id: s.stack_id for s in result.segments}
        self.stacks_meta = [
            {"id": s.id, "wall_id": s.wall_id, "offset": s.offset} for s in result.stacks
        ]
        return True

    def fixture_changed(self, item: dict[str, Any] | None, deadline_check=None) -> None:
        """A plumbing fixture moved or vanished: P-2 feet and P-1 scores are stale, so
        the inputs are re-resolved from the mutated layout and P-1..P-4 + E-4 re-run
        (device positions are kept — E-1..E-3 do not depend on fixtures)."""
        if item is None or "sanitary" not in (item.get("hookups") or []):
            return
        if self.refresh_inputs is None:
            return
        self.inputs = self.refresh_inputs(self.layout)
        if self.rerun_plumbing(deadline_check):
            self.rerun_routing(deadline_check)


def canonical(op: dict[str, Any] | None) -> str:
    return json.dumps(op["args"] if op else None, sort_keys=True)


def element_class(element_id: str, prisms: list[Prism]) -> tuple[str, int]:
    for p in prisms:
        if p.element_id == element_id:
            return p.cls, p.priority
    if element_id.startswith("revit:"):
        return "structure", 0
    raise MergeError("clash_pair_unknown", f"{element_id} is not in the merged plan")


def _geometry_of(element_id: str, prisms: list[Prism]) -> BaseGeometry | None:
    polys = [p.polygon for p in prisms if p.element_id == element_id]
    return unary_union(polys) if polys else None


def apply_pair(
    state: MergeState,
    a_id: str,
    b_id: str,
    kind: str,
    iteration: int,
    trigger: str,
    deadline_check=None,
) -> dict[str, Any]:
    """Resolve one clash pair: the lower-priority element re-plans. Returns the
    action record (also appended to the caller's list)."""
    prisms = state.prisms()
    # unknown ids are a contract error — except the plugin's `revit:<ElementId>` for
    # structure the merged plan never modelled (columns, risers, existing MEP)
    a_cls, a_pri = element_class(a_id, prisms)
    b_cls, b_pri = element_class(b_id, prisms)
    if a_cls == b_cls == "structure":
        raise MergeError("clash_pair_unknown", f"neither {a_id} nor {b_id} is in the merged plan")
    # lower = the one with the HIGHER priority number; ties -> blocked (unless exempt)
    if a_pri == b_pri:
        state.blocked = f"{a_id}~{b_id}: same clash priority {a_pri}"
        return _record(
            iteration, trigger, a_id, b_id, kind, b_id, b_pri, a_id, a_pri, "blocked", {}, False
        )
    if a_pri > b_pri:
        a_id, b_id, a_cls, b_cls, a_pri, b_pri = b_id, a_id, b_cls, a_cls, b_pri, a_pri
    higher_geom = _geometry_of(a_id, prisms)
    before = canonical(state.op_by_id(b_id))
    if b_cls == "furniture":
        action, params = _relegalize_furniture(state, b_id, higher_geom, deadline_check)
    elif b_cls == "device":
        action, params = _shift_device(state, b_id, higher_geom, a_id, deadline_check)
    elif b_cls == "conduit":
        action, params = _reroute_conduit(state, b_id, higher_geom, deadline_check)
    elif b_cls == "pipe":
        action, params = _relocate_stack(state, b_id, deadline_check)
    else:
        state.blocked = f"{a_id}~{b_id}: no re-plan action for class {b_cls}"
        action, params = "blocked", {}
    after = canonical(state.op_by_id(b_id))
    changed = before != after or b_id in state.dropped
    if not changed and action not in ("blocked",):
        # progress guarantee: escalate once, then drop
        if b_cls == "furniture":
            action, params = _relegalize_furniture(
                state, b_id, higher_geom, deadline_check, buffer_mm=OBSTACLE_BUFFER_ESCALATED_MM
            )
        elif b_cls == "device":
            action, params = _shift_device(
                state, b_id, higher_geom, a_id, deadline_check, tries=(5, 8)
            )
        elif b_cls == "conduit":
            action, params = _reroute_conduit(
                state, b_id, higher_geom, deadline_check, buffer_mm=OBSTACLE_BUFFER_ESCALATED_MM
            )
        after = canonical(state.op_by_id(b_id))
        changed = before != after or b_id in state.dropped
        if not changed:
            _drop(state, b_id)
            action, params, changed = "drop", {"reason": "no progress after escalation"}, True
    return _record(
        iteration, trigger, a_id, b_id, kind, b_id, b_pri, a_id, a_pri, action, params, changed
    )


def _record(
    iteration,
    trigger,
    a_id,
    b_id,
    kind,
    lower,
    lower_pri,
    higher,
    higher_pri,
    action,
    params,
    changed,
):
    return {
        "iteration": iteration,
        "trigger": trigger,
        "pair": {"a_id": a_id, "b_id": b_id, "kind": kind},
        "lower": lower,
        "lower_priority": lower_pri,
        "higher": higher,
        "higher_priority": higher_pri,
        "action": action,
        "params": params,
        "changed": changed,
    }


# ---- actions ---------------------------------------------------------------------


def _drop(state: MergeState, element_id: str) -> None:
    if element_id in state.dropped:
        return
    state.dropped.append(element_id)
    state.interior_ops = [op for op in state.interior_ops if op["args"].get("id") != element_id]
    state.mep_ops = [op for op in state.mep_ops if op["args"].get("id") != element_id]
    gone: dict[str, Any] | None = None
    for entry in state.layout.get("furniture", []):
        before = len(entry["items"])
        gone = gone or next((i for i in entry["items"] if i["id"] == element_id), None)
        entry["items"] = [i for i in entry["items"] if i["id"] != element_id]
        if len(entry["items"]) != before:
            state.interior_verbatim = False
    state.layout["furniture"] = [e for e in state.layout.get("furniture", []) if e["items"]]
    if element_id.startswith("E-"):
        state.rerun_routing()
    state.fixture_changed(gone)


def _relegalize_furniture(
    state: MergeState,
    item_id: str,
    higher_geom: BaseGeometry | None,
    deadline_check=None,
    buffer_mm: float = OBSTACLE_BUFFER_MM,
) -> tuple[str, dict[str, Any]]:
    items = state.furniture_items()
    target = next((i for i in items if i["id"] == item_id), None)
    if target is None:
        return "drop", {"reason": "item already gone"}
    others = [i for i in items if i["id"] != item_id]
    obstacles = [higher_geom.buffer(buffer_mm)] if higher_geom is not None else []
    trimmed = copy.deepcopy(state.layout)
    for entry in trimmed["furniture"]:
        entry["items"] = [i for i in entry["items"] if i["id"] != item_id]
    trimmed["furniture"] = [e for e in trimmed["furniture"] if e["items"]]
    outcome = legalize_furniture(
        [target], trimmed, deadline_check, preplaced=others, obstacles=obstacles
    )
    placed = [i for e in outcome.furniture for i in e["items"]]
    before = {"center": list(target["center"]), "rotation_deg": target["rotation_deg"]}
    if not placed:
        _drop(state, item_id)
        return "drop", {
            "reason": outcome.unplaced[0]["reason"] if outcome.unplaced else "unplaceable",
            "before": before,
        }
    new = placed[0]
    for entry in state.layout["furniture"]:
        for i, item in enumerate(entry["items"]):
            if item["id"] == item_id:
                entry["items"][i] = {k: v for k, v in new.items() if k != "room_id"}
    op = state.op_by_id(item_id)
    if op is not None:
        op["args"]["center"] = [round(new["center"][0], 1), round(new["center"][1], 1)]
        op["args"]["rotation_deg"] = new["rotation_deg"]
    after = {"center": list(new["center"]), "rotation_deg": new["rotation_deg"]}
    if after != before:
        state.interior_verbatim = False
        state.replan_deltas.append(
            {
                "id": item_id,
                "kind": "furniture",
                "from": before,
                "to": after,
                "reason": f"clash with higher-priority element (obstacle +{buffer_mm:.0f})",
            }
        )
    # validator oracle on the moved item
    errors = validate_layout(state.layout)
    if errors:
        _drop(state, item_id)
        return "drop", {
            "reason": "validator rejected the re-legalized item",
            "errors": errors[:3],
            "before": before,
        }
    if after != before:
        state.fixture_changed(new, deadline_check)
    return "relegalize_furniture", {
        "before": before,
        "after": after,
        "obstacle_buffer_mm": buffer_mm,
    }


def _shift_device(
    state: MergeState,
    device_id: str,
    higher_geom: BaseGeometry | None,
    higher_id: str,
    deadline_check=None,
    tries: tuple[int, int] = (1, 4),
) -> tuple[str, dict[str, Any]]:
    op = state.op_by_id(device_id)
    if op is None:
        return "drop", {"reason": "device already gone"}
    args = op["args"]
    wall = state.inputs.walls[args["host_wall_id"]]
    meta = state.devices_meta.get(device_id, {})
    room = state.inputs.rooms.get(meta.get("room_id", ""))
    if room is None:
        _drop(state, device_id)
        return "drop", {"reason": "device room unknown"}
    runs = wall_runs(state.layout, room, wall, float(args["height_afl"]), [])
    offset = float(args["offset"])
    if higher_geom is not None:
        proj = offset_of((higher_geom.centroid.x, higher_geom.centroid.y), wall)
        sign = 1.0 if offset >= proj else -1.0
    else:
        sign = 1.0
    others = [
        (o["args"]["host_wall_id"], float(o["args"]["offset"]), float(o["args"]["height_afl"]))
        for o in state.mep_ops
        if o["op"] == "place_device" and o["args"]["id"] != device_id
    ]
    for k in range(tries[0], tries[1] + 1):
        if deadline_check:
            deadline_check()
        trial = offset + sign * k * DEVICE_SHIFT_MM
        if not legal_on_runs(runs, trial):
            continue
        if any(
            w == args["host_wall_id"]
            and abs(t - trial) < DEVICE_B2B_MM
            and abs(h - float(args["height_afl"])) < DEVICE_B2B_MM
            for w, t, h in others
        ):
            continue
        before = {"offset": offset, "face": args["face"]}
        args["offset"] = round(trial, 1)
        args["face"] = room_face(state.inputs.polygons[room["id"]], wall, trial)
        state.rerun_routing(deadline_check)
        return "shift_device", {
            "before": before,
            "after": {"offset": args["offset"], "face": args["face"]},
            "k": k,
            "away_from": higher_id,
        }
    _drop(state, device_id)
    return "drop", {
        "reason": f"no legal shift within {tries[1]}x150 mm",
        "before": {"offset": offset},
    }


def _reroute_conduit(
    state: MergeState,
    conduit_id: str,
    higher_geom: BaseGeometry | None,
    deadline_check=None,
    buffer_mm: float = OBSTACLE_BUFFER_MM,
) -> tuple[str, dict[str, Any]]:
    if higher_geom is None:
        _drop(state, conduit_id)
        return "drop", {"reason": "no geometry to route around"}
    obstacle = higher_geom.buffer(buffer_mm)
    state.obstacles.append(obstacle)
    before = canonical(state.op_by_id(conduit_id))
    state.rerun_routing(deadline_check)
    after = canonical(state.op_by_id(conduit_id))
    params = {"obstacle_wkt": obstacle.wkt, "obstacle_buffer_mm": buffer_mm}
    if before == after:
        return "reroute_conduit", {**params, "note": "raceway unchanged"}
    return "reroute_conduit", params


def _relocate_stack(
    state: MergeState, pipe_id: str, deadline_check=None
) -> tuple[str, dict[str, Any]]:
    stack_ids = {s["id"] for s in state.stacks_meta}
    stack_id = pipe_id if pipe_id in stack_ids else state.segment_stack.get(pipe_id)
    stack = next((s for s in state.stacks_meta if s["id"] == stack_id), None)
    if stack is None:
        state.blocked = f"{pipe_id}: no stack to relocate"
        return "blocked", {}
    state.banned_walls.add(stack["wall_id"])
    if not state.rerun_plumbing(deadline_check):
        state.blocked = (
            f"{stack_id}: no candidate wall left after banning {sorted(state.banned_walls)}"
        )
        return "blocked", {"banned_walls": sorted(state.banned_walls)}
    state.rerun_routing(deadline_check)
    return "relocate_stack", {"banned_walls": sorted(state.banned_walls), "stack": stack_id}


# ---- replay (stateless /merge) ----------------------------------------------------


def replay_actions(
    state: MergeState, prior_actions: list[dict[str, Any]], deadline_check=None
) -> None:
    """Re-apply recorded actions from their params without searching again."""
    routing_dirty = False
    for act in prior_actions:
        if deadline_check:
            deadline_check()
        kind, lower, params = act.get("action"), act.get("lower"), act.get("params", {})
        if kind == "drop":
            _drop(state, lower)
        elif kind == "relegalize_furniture" and "after" in params:
            for entry in state.layout.get("furniture", []):
                for item in entry["items"]:
                    if item["id"] == lower:
                        item["center"] = list(params["after"]["center"])
                        item["rotation_deg"] = params["after"]["rotation_deg"]
            op = state.op_by_id(lower)
            if op is not None:
                op["args"]["center"] = [round(c, 1) for c in params["after"]["center"]]
                op["args"]["rotation_deg"] = params["after"]["rotation_deg"]
            state.interior_verbatim = False
            state.replan_deltas.append(
                {
                    "id": lower,
                    "kind": "furniture",
                    "from": params.get("before"),
                    "to": params["after"],
                    "reason": "replayed",
                }
            )
            moved = next((i for i in state.furniture_items() if i["id"] == lower), None)
            state.fixture_changed(moved, deadline_check)
            routing_dirty = True
        elif kind == "shift_device" and "after" in params:
            op = state.op_by_id(lower)
            if op is not None:
                op["args"]["offset"] = params["after"]["offset"]
                op["args"]["face"] = params["after"]["face"]
                routing_dirty = True
        elif kind == "reroute_conduit" and "obstacle_wkt" in params:
            state.obstacles.append(wkt.loads(params["obstacle_wkt"]))
            routing_dirty = True
        elif kind == "relocate_stack":
            state.banned_walls.update(params.get("banned_walls", []))
            state.rerun_plumbing(deadline_check)
            routing_dirty = True
    if routing_dirty:
        state.rerun_routing(deadline_check)


def foot_of(state: MergeState, device_id: str) -> tuple[float, float] | None:
    op = state.op_by_id(device_id)
    if op is None:
        return None
    return pt_on_wall(state.inputs.walls[op["args"]["host_wall_id"]], float(op["args"]["offset"]))
