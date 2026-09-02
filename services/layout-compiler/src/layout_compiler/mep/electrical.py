"""E-1 / E-2 / E-3 (PLAN.md Part G) plus the pinned extensions (docs/PHASE6_DESIGN.md
§3.3, PIN-12..21): receptacles per continuous run with the spacing kernel and the
300 mm dedupe, counter and bathroom GFCI, latch-side switches with a flagged
fallback ladder, corridor/laundry single-device rules, appliance receptacles
(receptacle_240 for 240 V hookups), the area-based GFCI rule, back-to-back
resolution, deterministic ids. No RNG, no clock; deadline polled per room."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import Point

from layout_compiler.geometry import pt_on_wall, wall_len
from layout_compiler.mep.constants import (
    APPLIANCE_SHIFT_MAX_MM,
    COORD_ROUND,
    DEVICE_B2B_MM,
    DEVICE_SHIFT_MM,
    DEVICE_SHIFT_TRIES,
    E1_DEDUPE_MM,
    E1_HEIGHT_AFL_MM,
    E1_INSET_MM,
    E1_MIN_RUN_MM,
    E2_BASIN_MAX_MM,
    E2_HEIGHT_AFL_MM,
    E2_INSET_MM,
    E2_SPACING_MM,
    E3_HEIGHT_AFL_MM,
    E3_JAMB_OFFSET_MM,
    E4_STACK_EXCLUSION_MM,
    EXTENSION_APPLIANCE_RECEPTACLES,
    HALLWAY_RECEPTACLE_MIN_EDGE_MM,
)
from layout_compiler.mep.inputs import (
    DeadlineCheck,
    MepInputs,
    ReviewItem,
    left_normal,
    offset_of,
    placed_items,
)
from layout_compiler.mep.runs import Interval, legal_on_runs, run_containing, wall_runs
from layout_compiler.swing import swing_side_normal

E1_PROGRAMS_EXCLUDED = ("closet", "bathroom", "powder", "corridor", "laundry")
GFCI_AREA_PROGRAMS = ("bathroom", "powder", "laundry")
RECEPTACLE_RULES = ("E-1", "E-2", "E-2-basin", "corridor", "laundry", "appliance")


@dataclass
class Device:
    kind: str
    rule: str
    room_id: str
    host_wall_id: str
    offset: float
    height_afl: float
    face: str
    run: Interval | None = None
    runs: list[Interval] | None = None
    source: str | None = None
    circuit: str = "120V"
    door_id: str | None = None
    id: str = ""

    def to_dict(self) -> dict[str, Any]:
        run = None
        if self.run:
            run = [round(self.run[0], COORD_ROUND), round(self.run[1], COORD_ROUND)]
        return {
            "id": self.id,
            "kind": self.kind,
            "rule": self.rule,
            "room_id": self.room_id,
            "host_wall_id": self.host_wall_id,
            "offset": round(self.offset, COORD_ROUND),
            "height_afl": self.height_afl,
            "face": self.face,
            "run": run,
            "source": self.source,
            "circuit": self.circuit,
            "door_id": self.door_id,
        }


@dataclass
class ElectricalResult:
    devices: list[Device]
    items: list[ReviewItem]
    counters: dict[str, int]


# ---- the spacing kernel ----------------------------------------------------------


def spacing_positions(
    length: float, inset: float, spacing: float, dedupe: bool = True
) -> list[float]:
    """E-1/E-2 kernel: runs shorter than 610 get nothing; N = max(1, ⌈(L−2a)/S⌉ + 1);
    N = 1 places the single device at L/2 (explicit branch — no division); otherwise
    xᵢ = a + i·(L−2a)/(N−1). Dedupe (PIN-14): consecutive positions closer than 300
    merge to their midpoint until no such pair remains (stack-based fixpoint)."""
    if length < E1_MIN_RUN_MM:
        return []
    n = max(1, math.ceil((length - 2 * inset) / spacing - 1e-12) + 1)
    if n == 1:
        xs = [length / 2]
    else:
        step = (length - 2 * inset) / (n - 1)
        xs = [inset + i * step for i in range(n)]
    if not dedupe:
        return xs
    out: list[float] = []
    for x in xs:
        out.append(x)
        while len(out) >= 2 and out[-1] - out[-2] < E1_DEDUPE_MM - 1e-9:
            b = out.pop()
            a = out.pop()
            out.append((a + b) / 2)
    return out


# ---- helpers ---------------------------------------------------------------------


def room_face(polygon: Any, wall: dict[str, Any], offset: float) -> str:
    """Which face of the wall the room is on ('left' | 'right' of start->end)."""
    fx, fy = pt_on_wall(wall, offset)
    nx, ny = left_normal(wall)
    if polygon.covers(Point(fx + nx, fy + ny)):
        return "left"
    if polygon.covers(Point(fx - nx, fy - ny)):
        return "right"
    return "left"


def _zones_for(stack_zones: list[tuple[str, float]], wall_id: str) -> list[Interval]:
    return [
        (off - E4_STACK_EXCLUSION_MM, off + E4_STACK_EXCLUSION_MM)
        for wid, off in stack_zones
        if wid == wall_id
    ]


def device_kind(inputs: MepInputs, room: dict[str, Any], wall_id: str, base: str) -> str:
    """PIN-19 area rule: on a kitchen counter wall, or anywhere in a bathroom/powder/
    laundry, every receptacle is a gfci; 240 V appliance receptacles stay receptacle_240."""
    if base in ("switch", "receptacle_240"):
        return base
    if room["program"] in GFCI_AREA_PROGRAMS:
        return "gfci"
    if room["program"] == "kitchen" and wall_id in inputs.counter_walls.get(room["id"], []):
        return "gfci"
    return base


def _first_legal(runs: list[Interval], offsets: list[float]) -> float | None:
    for off in offsets:
        if legal_on_runs(runs, off):
            return off
    return None


def _clip(runs: list[Interval], window: Interval) -> list[Interval]:
    out = []
    for t0, t1 in runs:
        a, b = max(t0, window[0]), min(t1, window[1])
        if b - a > 1.0:
            out.append((a, b))
    return out


def _longest_run(
    inputs: MepInputs, room: dict[str, Any], height: float, runs_for: Any
) -> tuple[str, Interval] | None:
    best: tuple[float, str, Interval] | None = None
    for wall_id in room["boundary_wall_ids"]:
        for run in runs_for(room, inputs.walls[wall_id], height):
            length = run[1] - run[0]
            if length >= E1_MIN_RUN_MM and (best is None or length > best[0]):
                best = (length, wall_id, run)
    return None if best is None else (best[1], best[2])


# ---- planner ---------------------------------------------------------------------


def plan_electrical(
    inputs: MepInputs,
    stack_zones: list[tuple[str, float]] | None = None,
    deadline_check: DeadlineCheck = None,
) -> ElectricalResult:
    layout = inputs.layout
    zones = stack_zones or []
    items: list[ReviewItem] = []
    counters = {"shift_tries": 0, "b2b_shifts": 0, "b2b_drops": 0}
    e1: list[Device] = []
    corridor: list[Device] = []
    laundry: list[Device] = []
    counter: list[Device] = []
    basin: list[Device] = []
    appliances: list[Device] = []
    switches: list[Device] = []
    spacing_ok = "outlet_spacing_invalid" not in inputs.blocking()

    def runs_for(
        room: dict[str, Any], wall: dict[str, Any], height: float, extra: Any = ()
    ) -> list[Interval]:
        return wall_runs(layout, room, wall, height, _zones_for(zones, wall["id"]), extra)

    def make(
        rule: str,
        room: dict[str, Any],
        wall: dict[str, Any],
        offset: float,
        height: float,
        runs: list[Interval],
        base: str = "receptacle",
        **extra: Any,
    ) -> Device:
        return Device(
            kind=device_kind(inputs, room, wall["id"], base),
            rule=rule,
            room_id=room["id"],
            host_wall_id=wall["id"],
            offset=offset,
            height_afl=height,
            face=room_face(inputs.polygons[room["id"]], wall, offset),
            run=run_containing(runs, offset),
            runs=runs,
            **extra,
        )

    for room_id in sorted(inputs.rooms):
        if deadline_check:
            deadline_check()
        room = inputs.rooms[room_id]
        program = room["program"]
        if program in ("closet", "bathroom", "powder"):
            continue  # closets get nothing; bathrooms only the basin rule below
        if program == "corridor":  # PIN-16: NEC 210.52(H) hallway receptacle
            ring = [*room["boundary"], room["boundary"][0]]
            longest_edge = max(math.dist(a, b) for a, b in zip(ring, ring[1:], strict=False))
            if longest_edge >= HALLWAY_RECEPTACLE_MIN_EDGE_MM:
                found = _longest_run(inputs, room, E1_HEIGHT_AFL_MM, runs_for)
                if found is not None:
                    wall = inputs.walls[found[0]]
                    runs = runs_for(room, wall, E1_HEIGHT_AFL_MM)
                    mid = (found[1][0] + found[1][1]) / 2
                    corridor.append(make("corridor", room, wall, mid, E1_HEIGHT_AFL_MM, runs))
            continue
        if program == "laundry":  # PIN-17: NEC 210.52(F) one gfci
            found = _longest_run(inputs, room, E2_HEIGHT_AFL_MM, runs_for)
            if found is not None:
                wall = inputs.walls[found[0]]
                runs = runs_for(room, wall, E2_HEIGHT_AFL_MM)
                mid = (found[1][0] + found[1][1]) / 2
                laundry.append(make("laundry", room, wall, mid, E2_HEIGHT_AFL_MM, runs, "gfci"))
            continue
        # ---- E-1 on every other program (counter intervals removed from the runs, PIN-15)
        if spacing_ok:
            for wall_id in room["boundary_wall_ids"]:
                wall = inputs.walls[wall_id]
                counters_here = inputs.counter_runs.get((room_id, wall_id), [])
                runs = runs_for(room, wall, E1_HEIGHT_AFL_MM, counters_here)
                for t0, t1 in runs:
                    for x in spacing_positions(t1 - t0, E1_INSET_MM, inputs.outlet_spacing):
                        e1.append(make("E-1", room, wall, t0 + x, E1_HEIGHT_AFL_MM, runs))
        # ---- E-2 counter circuit on kitchen counter walls
        if program == "kitchen":
            for wall_id in inputs.counter_walls.get(room_id, []):
                wall = inputs.walls[wall_id]
                runs = runs_for(room, wall, E2_HEIGHT_AFL_MM)
                for interval in inputs.counter_runs.get((room_id, wall_id), []):
                    for t0, t1 in _clip(runs, interval):
                        for x in spacing_positions(t1 - t0, E2_INSET_MM, E2_SPACING_MM):
                            counter.append(
                                make("E-2", room, wall, t0 + x, E2_HEIGHT_AFL_MM, runs, "gfci")
                            )

    # ---- E-2 basin rule: a gfci within 914 mm of every bathroom/powder lav
    for f in inputs.fixtures:
        room = inputs.rooms[f.room_id]
        if f.kind != "lav" or room["program"] not in ("bathroom", "powder"):
            continue
        wall = inputs.walls[f.host_wall_id]
        foot = offset_of(f.center, wall)
        runs = runs_for(room, wall, E2_HEIGHT_AFL_MM)
        candidates = [
            foot + sign * k * 50.0
            for k in range(6, int(E2_BASIN_MAX_MM // 50) + 1)
            for sign in (1.0, -1.0)
        ]
        chosen = _first_legal(runs, candidates)
        if chosen is None:
            items.append(
                ReviewItem(
                    "bath_gfci_unplaceable",
                    "info",
                    [f.id],
                    f"no legal 1150 mm position within {E2_BASIN_MAX_MM:.0f} mm of {f.id}'s basin",
                )
            )
            continue
        basin.append(
            make("E-2-basin", room, wall, chosen, E2_HEIGHT_AFL_MM, runs, "gfci", source=f.id)
        )

    # ---- appliance receptacles (PIN-20, extension)
    if EXTENSION_APPLIANCE_RECEPTACLES:
        for room_id, item in placed_items(layout):
            hookups = item.get("hookups") or []
            volts = [h for h in hookups if h in ("electrical_120", "electrical_240")]
            if not volts:
                continue
            room = inputs.rooms[room_id]
            wall = inputs.walls[inputs.host_walls[item["id"]]]
            centre = (item["center"][0], item["center"][1])
            foot = max(0.0, min(wall_len(wall), offset_of(centre, wall)))
            runs = runs_for(room, wall, E1_HEIGHT_AFL_MM)  # counter intervals stay legal here
            steps = int(APPLIANCE_SHIFT_MAX_MM // 50)
            candidates = [foot] + [
                foot + s * k * 50.0 for k in range(1, steps + 1) for s in (1.0, -1.0)
            ]
            chosen = _first_legal(runs, candidates)
            base = "receptacle_240" if "electrical_240" in volts else "receptacle"
            if "electrical_240" in volts:
                items.append(
                    ReviewItem(
                        "electrical_240",
                        "info",
                        [item["id"]],
                        f"{item['id']} ({item['kind']}) needs a dedicated 240 V circuit",
                    )
                )
            if chosen is None:
                items.append(
                    ReviewItem(
                        "appliance_receptacle_unplaceable",
                        "info",
                        [item["id"]],
                        f"no legal run point within {APPLIANCE_SHIFT_MAX_MM:.0f} mm of "
                        f"{item['id']}",
                    )
                )
                continue
            if abs(chosen - foot) > 1e-9:
                items.append(
                    ReviewItem(
                        "appliance_receptacle_shifted",
                        "info",
                        [item["id"]],
                        f"{item['id']}: receptacle shifted {abs(chosen - foot):.0f} mm to a legal "
                        "run point",
                    )
                )
            appliances.append(
                make(
                    "appliance",
                    room,
                    wall,
                    chosen,
                    E1_HEIGHT_AFL_MM,
                    runs,
                    base,
                    source=item["id"],
                    circuit="240V" if base == "receptacle_240" else "120V",
                )
            )

    # ---- E-3 switches: latch side, 150 from the jamb, 1220 AFF, swept-side room
    rooms_with_switch: set[str] = set()
    for door in sorted(layout["doors"], key=lambda d: d["id"]):
        wall = inputs.walls[door["host_wall_id"]]
        half = door["width"] / 2
        swing_left = door.get("swing", "L") == "L"
        hinge_t = door["offset"] - half if swing_left else door["offset"] + half
        latch_t = door["offset"] + half if swing_left else door["offset"] - half
        nx, ny = swing_side_normal(door, wall)
        mx, my = pt_on_wall(wall, door["offset"])
        room = _room_at(inputs, (mx + nx, my + ny), wall["id"]) or _room_at(
            inputs, (mx - nx, my - ny), wall["id"]
        )
        if room is None:
            items.append(
                ReviewItem(
                    "switch_unplaceable",
                    "info",
                    [door["id"]],
                    f"{door['id']}: no room on either side of the door",
                )
            )
            continue
        sign = 1.0 if latch_t > hinge_t else -1.0
        runs = runs_for(room, wall, E3_HEIGHT_AFL_MM)
        placed: Device | None = None
        latch_offset = latch_t + sign * E3_JAMB_OFFSET_MM
        if legal_on_runs(runs, latch_offset):
            placed = make(
                "E-3",
                room,
                wall,
                latch_offset,
                E3_HEIGHT_AFL_MM,
                runs,
                "switch",
                door_id=door["id"],
            )
        else:
            corner = tuple(wall["end"]) if sign > 0 else tuple(wall["start"])
            adjacent = _adjacent_wall_at(inputs, room, wall["id"], corner)
            if adjacent is not None:
                at_start = math.dist(adjacent["start"], corner) <= 1.0
                adj_offset = (
                    E3_JAMB_OFFSET_MM if at_start else wall_len(adjacent) - E3_JAMB_OFFSET_MM
                )
                adj_runs = runs_for(room, adjacent, E3_HEIGHT_AFL_MM)
                if legal_on_runs(adj_runs, adj_offset):
                    placed = make(
                        "E-3",
                        room,
                        adjacent,
                        adj_offset,
                        E3_HEIGHT_AFL_MM,
                        adj_runs,
                        "switch",
                        door_id=door["id"],
                    )
                    items.append(
                        ReviewItem(
                            "switch_corner_fallback",
                            "info",
                            [door["id"], adjacent["id"]],
                            f"{door['id']}: latch side blocked; switch on the adjacent wall "
                            f"{adjacent['id']} at the latch corner",
                        )
                    )
            if placed is None:
                hinge_offset = hinge_t - sign * E3_JAMB_OFFSET_MM
                if legal_on_runs(runs, hinge_offset):
                    placed = make(
                        "E-3",
                        room,
                        wall,
                        hinge_offset,
                        E3_HEIGHT_AFL_MM,
                        runs,
                        "switch",
                        door_id=door["id"],
                    )
                    items.append(
                        ReviewItem(
                            "switch_hinge_side",
                            "info",
                            [door["id"]],
                            f"{door['id']}: switch placed on the hinge side",
                        )
                    )
        if placed is None:
            items.append(
                ReviewItem(
                    "switch_unplaceable",
                    "info",
                    [door["id"]],
                    f"{door['id']}: no legal switch position on either jamb or the latch corner",
                )
            )
            continue
        switches.append(placed)
        rooms_with_switch.add(room["id"])

    # ---- emission order, back-to-back resolution, ids
    ordered = [*e1, *corridor, *laundry, *counter, *basin, *appliances, *switches]
    accepted: list[Device] = []
    for dev in ordered:
        conflict = _b2b_conflict(dev, accepted)
        if conflict is None:
            accepted.append(dev)
            continue
        moved = None
        for k in range(1, DEVICE_SHIFT_TRIES + 1):
            counters["shift_tries"] += 1
            trial = dev.offset + k * DEVICE_SHIFT_MM
            if dev.runs is not None and legal_on_runs(dev.runs, trial):
                probe = Device(**{**dev.__dict__, "offset": trial})
                if _b2b_conflict(probe, accepted) is None:
                    moved = trial
                    break
        if moved is None:
            counters["b2b_drops"] += 1
            items.append(
                ReviewItem(
                    "device_backtoback_dropped",
                    "info",
                    [dev.rule, dev.host_wall_id],
                    f"{dev.rule} device on {dev.host_wall_id} @ {dev.offset:.0f} dropped: "
                    f"back-to-back with {conflict.rule} and no legal shift",
                )
            )
            continue
        counters["b2b_shifts"] += 1
        dev.offset = moved
        dev.run = run_containing(dev.runs or [], moved)
        dev.face = room_face(inputs.polygons[dev.room_id], inputs.walls[dev.host_wall_id], moved)
        items.append(
            ReviewItem(
                "device_backtoback_shifted",
                "info",
                [dev.host_wall_id],
                f"{dev.rule} device on {dev.host_wall_id} shifted to {moved:.0f} "
                f"(back-to-back with {conflict.rule})",
            )
        )
        accepted.append(dev)
    for i, dev in enumerate(accepted, start=1):
        dev.id = f"E-{i:03d}"

    # ---- room coverage notes
    for room_id in sorted(inputs.rooms):
        room = inputs.rooms[room_id]
        if room["program"] == "closet":
            continue
        if not any(d.room_id == room_id and d.rule in RECEPTACLE_RULES for d in accepted):
            items.append(
                ReviewItem(
                    "room_without_receptacle",
                    "info",
                    [room_id],
                    f"{room_id} ({room['program']}) ends with no receptacle",
                )
            )
        if room_id not in rooms_with_switch:
            items.append(
                ReviewItem(
                    "room_without_switch",
                    "info",
                    [room_id],
                    f"{room_id} ({room['program']}) has no switched door",
                )
            )
    return ElectricalResult(accepted, items, counters)


def _room_at(inputs: MepInputs, point: tuple[float, float], wall_id: str) -> dict[str, Any] | None:
    p = Point(point)
    for room_id in sorted(inputs.rooms):
        room = inputs.rooms[room_id]
        if wall_id in room["boundary_wall_ids"] and inputs.polygons[room_id].covers(p):
            return room
    return None


def _adjacent_wall_at(
    inputs: MepInputs, room: dict[str, Any], host_id: str, corner: tuple[float, float]
) -> dict[str, Any] | None:
    for wall_id in room["boundary_wall_ids"]:
        if wall_id == host_id:
            continue
        wall = inputs.walls[wall_id]
        if math.dist(wall["start"], corner) <= 1.0 or math.dist(wall["end"], corner) <= 1.0:
            return wall
    return None


def _b2b_conflict(dev: Device, accepted: list[Device]) -> Device | None:
    for other in accepted:
        if (
            other.host_wall_id == dev.host_wall_id
            and abs(other.offset - dev.offset) < DEVICE_B2B_MM
            and abs(other.height_afl - dev.height_afl) < DEVICE_B2B_MM
        ):
            return other
    return None
