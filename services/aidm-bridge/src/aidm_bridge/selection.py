"""Deterministic finish-selection validator (docs/PHASE7_DESIGN.md P7-08, P7-14, §3.4): the
designer's per-room / per-element SKU picks become the set_parameter ops of Commit #3 — or
a sorted list of blocking codes and NO ops. Total (every non-shape failure is a review
item), pure (no clock, no environment, no randomness), ordered (ops by target then param)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import jsonschema

from aidm_bridge.catalogs import (
    catalog_version as products_catalog_version,
)
from aidm_bridge.catalogs import (
    param_allowlist,
    plumbing_fixtures,
    set_parameter_schema,
    sku_index,
)
from aidm_bridge.csi import surface_of

PLACEHOLDER_MARK = "_PLACEHOLDER"
PARAM_SKU = "CHPT_Product_SKU"
PARAM_SPEC = "CHPT_Spec_Section"
PARAM_MATERIAL = "CHPT_Finish_Material"
PARAM_RENDER_REF = "CHPT_Render_Ref"
PARAM_COMMENTS = "Comments"
MATERIAL_PARAM_CATEGORIES = frozenset({"walls", "casework"})
APPLIANCE_KINDS = frozenset({"dishwasher", "washer"})


class SelectionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class LayoutIndex:
    walls: dict[str, dict[str, Any]]
    doors: dict[str, dict[str, Any]]
    windows: dict[str, dict[str, Any]]
    casework: dict[str, dict[str, Any]]
    rooms: dict[str, dict[str, Any]]
    items: dict[str, dict[str, Any]]  # furniture items with resolved hookups + room_id
    room_walls: dict[str, list[str]] = field(default_factory=dict)
    wall_rooms: dict[str, list[str]] = field(default_factory=dict)


def index_layout(layout: dict[str, Any]) -> LayoutIndex:
    table = plumbing_fixtures()
    items: dict[str, dict[str, Any]] = {}
    for group in layout.get("furniture", []):
        for item in group.get("items", []):
            hookups = item.get("hookups")
            if hookups is None:
                hookups = table.get(item.get("kind", ""), {}).get("hookups", [])
            items[item["id"]] = {**item, "hookups": list(hookups), "room_id": group.get("room_id")}
    index = LayoutIndex(
        walls={w["id"]: w for w in layout.get("walls", [])},
        doors={d["id"]: d for d in layout.get("doors", [])},
        windows={n["id"]: n for n in layout.get("windows", [])},
        casework={k["id"]: k for k in layout.get("casework", []) or []},
        rooms={r["id"]: r for r in layout.get("rooms", [])},
        items=items,
    )
    for room_id, room in index.rooms.items():
        walls = list(room.get("boundary_wall_ids", []))
        index.room_walls[room_id] = walls
        for wall_id in walls:
            index.wall_rooms.setdefault(wall_id, []).append(room_id)
    for wall_id in index.wall_rooms:
        index.wall_rooms[wall_id].sort()
    return index


def target_category(target_id: str, index: LayoutIndex) -> str | None:
    """The allowlist category vocabulary of a target id (the gateway uses the same prefix
    rule; F- items are plumbing when their hookups include sanitary)."""
    if target_id.startswith("W-"):
        return "walls"
    if target_id.startswith("D-"):
        return "doors"
    if target_id.startswith("N-"):
        return "windows"
    if target_id.startswith("K-"):
        return "casework"
    if target_id.startswith("F-"):
        item = index.items.get(target_id)
        return "plumbing" if item and "sanitary" in item["hookups"] else "furniture"
    if target_id.startswith("E-"):
        return "electrical"
    return None


def _item(code: str, severity: str, refs: list[str], message: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "refs": list(refs), "message": message}


def validate_selection(
    layout: dict[str, Any],
    id_map_ids: list[str],
    finish_tier: str,
    catalog_version: str,
    render_ref: str | None,
    selection: dict[str, Any],
    allow_placeholders: bool = False,
) -> dict[str, Any]:
    index = index_layout(layout)
    ids = set(id_map_ids)
    skus = sku_index()
    allow = param_allowlist()
    items: list[dict[str, Any]] = []
    per_target: dict[str, dict[str, Any]] = {}

    if catalog_version != products_catalog_version():
        items.append(
            _item(
                "catalog_version_mismatch",
                "blocking",
                [catalog_version],
                f"catalog is {products_catalog_version()}",
            )
        )

    overrides: dict[str, tuple[str, str]] = {}
    for ov in selection.get("overrides", []):
        if ov["target"] in overrides:
            items.append(_item("duplicate_override", "blocking", [ov["target"]], "two overrides"))
            continue
        overrides[ov["target"]] = (ov["sku"], ov["reason"])
    overrides_used: set[str] = set()

    # ---- resolve every slot to (target, category, expected surface, sku, rooms) ----------
    Target = tuple[str, str, str, str, list[str]]
    targets: list[Target] = []
    seen_targets: set[str] = set()

    def check_sku(target: str, sku: str, expected_surface: str) -> dict[str, Any] | None:
        row = skus.get(sku)
        if row is None:
            items.append(_item("unknown_sku", "blocking", [target, sku], "not in products.json"))
            return None
        if PLACEHOLDER_MARK in sku and not allow_placeholders:
            items.append(_item("placeholder_sku", "blocking", [target, sku], "placeholder SKU"))
            return None
        surface = surface_of(row["csi_section"])
        if surface is None:
            items.append(_item("sku_not_selectable", "blocking", [target, sku], "unmapped csi"))
            return None
        if surface != expected_surface:
            items.append(
                _item(
                    "surface_mismatch",
                    "blocking",
                    [target, sku],
                    f"{sku} is a {surface} SKU, target needs {expected_surface}",
                )
            )
            return None
        if row["finish_tier"] != finish_tier:
            ov = overrides.get(target)
            if ov and ov[0] == sku:
                overrides_used.add(target)
                items.append(
                    _item("tier_override", "info", [target, sku], f"{row['finish_tier']}: {ov[1]}")
                )
            else:
                items.append(
                    _item(
                        "tier_mismatch",
                        "blocking",
                        [target, sku],
                        f"{row['finish_tier']} SKU on a {finish_tier} project (no override)",
                    )
                )
                return None
        return row

    def add_target(target: str, category: str, surface: str, sku: str, rooms: list[str]) -> None:
        if target in seen_targets:
            items.append(_item("duplicate_target", "blocking", [target], "selected twice"))
            return
        seen_targets.add(target)
        if check_sku(target, sku, surface) is not None:
            targets.append((target, category, surface, sku, rooms))

    for room_sel in selection.get("rooms", []):
        room_id = room_sel["room_id"]
        if room_id not in index.rooms:
            items.append(_item("unknown_target", "blocking", [room_id], "room not in layout"))
            continue
        sku = room_sel.get("wall_sku")
        if sku is None:
            continue
        if room_id in seen_targets:
            items.append(_item("duplicate_target", "blocking", [room_id], "selected twice"))
            continue
        seen_targets.add(room_id)
        if check_sku(room_id, sku, "wall") is not None:
            targets.append((room_id, "walls", "wall", sku, [room_id]))

    for sel in selection.get("casework", []):
        if sel["id"] not in index.casework or sel["id"] not in ids:
            items.append(
                _item("unknown_target", "blocking", [sel["id"]], "casework not in layout/id-map")
            )
            continue
        add_target(sel["id"], "casework", "casework", sel["sku"], [])
    for sel in selection.get("doors", []):
        if sel["id"] not in index.doors or sel["id"] not in ids:
            items.append(
                _item("unknown_target", "blocking", [sel["id"]], "door not in layout/id-map")
            )
            continue
        add_target(sel["id"], "doors", "door", sel["sku"], [])
    for sel in selection.get("plumbing_fixtures", []):
        item = index.items.get(sel["id"])
        if item is None or sel["id"] not in ids:
            items.append(
                _item("unknown_target", "blocking", [sel["id"]], "item not in layout/id-map")
            )
            continue
        if "sanitary" not in item["hookups"]:
            items.append(
                _item("not_a_plumbing_fixture", "blocking", [sel["id"]], "no sanitary hookup")
            )
            continue
        if item.get("kind") in APPLIANCE_KINDS:
            items.append(
                _item(
                    "appliance_not_selectable", "info", [sel["id"]], "appliances have no v1 surface"
                )
            )
            per_target[sel["id"]] = {
                "category": "plumbing",
                "surface": None,
                "sku": sel["sku"],
                "status": "skipped",
                "params": [],
                "rooms": [],
            }
            continue
        add_target(sel["id"], "plumbing", "plumbing_fixture", sel["sku"], [])

    for target in overrides:
        if target not in overrides_used and target not in seen_targets:
            items.append(
                _item("override_unused", "info", [target], "override names no selected target")
            )

    # ---- walls: resolve per-room picks onto wall elements -----------------------------
    wall_choice: dict[str, dict[str, str]] = {}  # wall -> {room -> sku}
    for target, _category, surface, sku, _rooms in targets:
        if surface != "wall":
            continue
        for wall_id in index.room_walls.get(target, []):
            if wall_id not in index.walls or wall_id not in ids:
                items.append(
                    _item(
                        "unknown_target", "blocking", [wall_id, target], "wall not in layout/id-map"
                    )
                )
                continue
            wall_choice.setdefault(wall_id, {})[target] = sku

    # ---- emission --------------------------------------------------------------------
    ops: list[dict[str, Any]] = []
    if render_ref is None:
        items.append(
            _item(
                "render_ref_missing", "info", [], "no approved render ref; CHPT_Render_Ref omitted"
            )
        )

    def emit(target: str, category: str, params: list[tuple[str, str]]) -> list[str]:
        written: list[str] = []
        for param, value in params:
            entry = allow.get(param)
            cats = set(entry.get("categories", [])) if entry else set()
            if entry is None or ("*" not in cats and category not in cats):
                items.append(
                    _item(
                        "param_not_allowed",
                        "blocking",
                        [target, param],
                        f"{param} not allowlisted for {category}",
                    )
                )
                continue
            ops.append(
                {
                    "op": "set_parameter",
                    "args": {"target_id": target, "param": param, "value": value},
                }
            )
            written.append(param)
        return written

    def finish_params(row: dict[str, Any], category: str) -> list[tuple[str, str]]:
        params = [(PARAM_SKU, row["sku"]), (PARAM_SPEC, row["csi_section"])]
        if category in MATERIAL_PARAM_CATEGORIES:
            params.append((PARAM_MATERIAL, f"{row['manufacturer']} {row['model']}"))
            if render_ref is not None:
                params.append((PARAM_RENDER_REF, render_ref))
        return params

    for wall_id in sorted(wall_choice):
        choices = wall_choice[wall_id]
        distinct = sorted(set(choices.values()))
        rooms = sorted(choices)
        if len(distinct) == 1:
            row = skus[distinct[0]]
            written = emit(wall_id, "walls", finish_params(row, "walls"))
            per_target[wall_id] = {
                "category": "walls",
                "surface": "wall",
                "sku": distinct[0],
                "status": "applied",
                "params": written,
                "rooms": rooms,
            }
        else:
            note = "finish conflict: " + " / ".join(f"{room} {choices[room]}" for room in rooms)
            written = emit(wall_id, "walls", [(PARAM_COMMENTS, note)])
            items.append(_item("wall_finish_conflict", "info", [wall_id, *rooms], note))
            per_target[wall_id] = {
                "category": "walls",
                "surface": "wall",
                "sku": None,
                "status": "conflict",
                "params": written,
                "rooms": rooms,
            }

    for target, category, surface, sku, rooms in targets:
        if surface == "wall":
            per_target[target] = {
                "category": "walls",
                "surface": "wall",
                "sku": sku,
                "status": "applied",
                "params": [],
                "rooms": rooms,
            }
            continue
        written = emit(target, category, finish_params(skus[sku], category))
        per_target[target] = {
            "category": category,
            "surface": surface,
            "sku": sku,
            "status": "applied",
            "params": written,
            "rooms": rooms,
        }

    blocking = sorted({i["code"] for i in items if i["severity"] == "blocking"})
    if blocking:
        for entry in per_target.values():
            if entry["status"] == "applied":
                entry["status"] = "blocked"
        ops = []
    ops.sort(key=lambda op: (op["args"]["target_id"], op["args"]["param"]))
    validate_ops(ops)
    items.sort(key=lambda i: (i["severity"], i["code"], i["refs"]))
    return {
        "ops": ops,
        "review_items": items,
        "blocking": blocking,
        "diagnostics": {
            "per_target": dict(sorted(per_target.items())),
            "counts": {
                "targets": len(per_target),
                "walls_applied": sum(
                    1
                    for v in per_target.values()
                    if v["surface"] == "wall" and v["status"] == "applied" and v["params"]
                ),
                "walls_conflict": sum(1 for v in per_target.values() if v["status"] == "conflict"),
                "ops": len(ops),
                "blocking": len(blocking),
                "info": sum(1 for i in items if i["severity"] == "info"),
            },
        },
    }


def validate_ops(ops: list[dict[str, Any]]) -> None:
    """Every emitted op must satisfy the registry set_parameter args_schema and the
    allowlist name (a hard internal error otherwise — the emission is ours)."""
    schema = set_parameter_schema()
    allowed = set(param_allowlist())
    for op in ops:
        try:
            jsonschema.validate(op["args"], schema)
        except jsonschema.ValidationError as err:
            raise SelectionError(
                "selection_internal", f"emitted op invalid: {err.message}"
            ) from err
        if op["op"] != "set_parameter" or op["args"]["param"] not in allowed:
            raise SelectionError("selection_internal", f"emitted op off the allowlist: {op}")
