"""In-memory model + op application. Mirrors the plugin's real failure modes: unknown
catalog types, duplicate ids, out-of-host offsets, SI-8 immutability of existing
elements. Ops are applied to a deep COPY per envelope (executor.py) so failure is
all-or-nothing — the sim's TransactionGroup."""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from revit_sim import placement

CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "packages" / "contracts"


class OpError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class Catalogs:
    wall_types: set[str]
    door_types: set[str]
    window_types: set[str]
    param_allowlist: set[str]
    # Phase 6: wall thickness by type (device face hosting), MEP vocabulary and the
    # shared clash law inputs (catalogs/clash_prisms.json — ONE law, three executors)
    wall_thickness_mm: dict[str, float] = field(default_factory=dict)
    pipe_types: set[str] = field(default_factory=set)
    conduit_type: str | None = None
    family_kinds: dict[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    clash_prisms: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, contracts_dir: Path = CONTRACTS_DIR) -> Catalogs:
        asbuilt = json.loads((contracts_dir / "catalogs" / "asbuilt_types.json").read_text())
        newc = json.loads((contracts_dir / "catalogs" / "new_construction_types.json").read_text())
        allowlist = json.loads((contracts_dir / "ops" / "param_allowlist.json").read_text())
        mep = json.loads((contracts_dir / "catalogs" / "mep_types.json").read_text())
        prisms = json.loads((contracts_dir / "catalogs" / "clash_prisms.json").read_text())
        family_kinds: dict[tuple[str, str], tuple[str, ...]] = {}
        for family in newc.get("families", []):
            for ftype in family["types"]:
                kinds = ftype.get("kinds", family.get("kinds", []))
                family_kinds[(family["revit_family"], ftype["revit_type"])] = tuple(kinds)
        return cls(
            wall_types={t["revit_type"] for t in asbuilt["types"]}
            | {t["revit_type"] for t in newc["walls"]},
            door_types={t["revit_type"] for t in asbuilt.get("doors", [])}
            | {t["revit_type"] for t in newc["doors"]},
            window_types={t["revit_type"] for t in asbuilt.get("windows", [])}
            | {t["revit_type"] for t in newc["windows"]},
            param_allowlist={p["name"] for p in allowlist["params"]},
            wall_thickness_mm={t["revit_type"]: float(t["thickness_mm"]) for t in asbuilt["types"]}
            | {t["revit_type"]: float(t["thickness_mm"]) for t in newc["walls"]},
            pipe_types=set(mep["pipe_types"].values()),
            conduit_type=mep.get("conduit_type"),
            family_kinds=family_kinds,
            clash_prisms=prisms,
        )


@dataclass
class SimModel:
    levels: dict[str, dict[str, Any]] = field(default_factory=dict)
    walls: dict[str, dict[str, Any]] = field(default_factory=dict)
    doors: dict[str, dict[str, Any]] = field(default_factory=dict)
    windows: dict[str, dict[str, Any]] = field(default_factory=dict)
    families: dict[str, dict[str, Any]] = field(default_factory=dict)
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)
    pipes: dict[str, dict[str, Any]] = field(default_factory=dict)
    conduits: dict[str, dict[str, Any]] = field(default_factory=dict)
    pointclouds: list[str] = field(default_factory=list)
    demolished: set[str] = field(default_factory=set)
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)

    def clone(self) -> SimModel:
        return copy.deepcopy(self)

    def all_ids(self) -> set[str]:
        return (
            set(self.levels)
            | set(self.walls)
            | set(self.doors)
            | set(self.windows)
            | set(self.families)
            | set(self.devices)
            | set(self.pipes)
            | set(self.conduits)
        )

    # ---- op handlers -------------------------------------------------------

    def _require_new_id(self, element_id: str) -> None:
        if element_id in self.all_ids():
            raise OpError("duplicate_id", element_id)

    def _wall(self, wall_id: str) -> dict[str, Any]:
        wall = self.walls.get(wall_id)
        if wall is None:
            raise OpError("unknown_host", wall_id)
        return wall

    def _check_hosted_offset(self, wall: dict[str, Any], offset: float, width: float) -> None:
        sx, sy = wall["start"]
        ex, ey = wall["end"]
        length = math.hypot(ex - sx, ey - sy)
        if offset - width / 2 < 0 or offset + width / 2 > length:
            raise OpError("offset_outside_host", f"offset {offset} on wall length {length:.1f}")

    def apply(self, op: str, args: dict[str, Any], catalogs: Catalogs) -> str | None:
        """Apply one op; returns the logical id of a created element (for id_map_delta)."""
        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            raise OpError("unknown_op", op)
        return handler(args, catalogs)

    def _op_create_level(self, args: dict[str, Any], _c: Catalogs) -> str:
        name = args["name"]
        if name in self.levels:
            raise OpError("duplicate_id", name)
        self.levels[name] = {"elevation": args["elevation"]}
        return name

    def _op_create_wall(self, args: dict[str, Any], catalogs: Catalogs) -> str:
        self._require_new_id(args["id"])
        if args["revit_type"] not in catalogs.wall_types:
            raise OpError("unknown_revit_type", args["revit_type"])
        self.walls[args["id"]] = {
            "start": args["start"],
            "end": args["end"],
            "revit_type": args["revit_type"],
            "height": args["height"],
            "phase": args["phase"],
            "flags": args.get("flags", {}),
        }
        return args["id"]

    def _op_create_door(self, args: dict[str, Any], catalogs: Catalogs) -> str:
        self._require_new_id(args["id"])
        if args["revit_type"] not in catalogs.door_types:
            raise OpError("unknown_revit_type", args["revit_type"])
        wall = self._wall(args["host_wall_id"])
        self._check_hosted_offset(wall, args["offset"], args["width"])
        point = placement.place(
            "centerline", tuple(wall["start"]), tuple(wall["end"]), 0, args["offset"], 0
        )
        self.doors[args["id"]] = {**args, "point": point}
        return args["id"]

    def _op_create_window(self, args: dict[str, Any], catalogs: Catalogs) -> str:
        self._require_new_id(args["id"])
        if args["revit_type"] not in catalogs.window_types:
            raise OpError("unknown_revit_type", args["revit_type"])
        wall = self._wall(args["host_wall_id"])
        self._check_hosted_offset(wall, args["offset"], args["width"])
        point = placement.place(
            "centerline",
            tuple(wall["start"]),
            tuple(wall["end"]),
            0,
            args["offset"],
            args["sill_height"],
        )
        self.windows[args["id"]] = {**args, "point": point}
        return args["id"]

    def _op_place_family(self, args: dict[str, Any], _c: Catalogs) -> str:
        self._require_new_id(args["id"])
        self.families[args["id"]] = dict(args)
        return args["id"]

    def _op_place_device(self, args: dict[str, Any], catalogs: Catalogs) -> str:
        self._require_new_id(args["id"])
        wall = self._wall(args["host_wall_id"])
        self._check_hosted_offset(wall, args["offset"], 0)
        # Phase 6: the op names the face (left|right of start->end) and the point sits on
        # that face at the host's CATALOG thickness — the same Placement law the plugin
        # pins against fixtures/placement (Phase 1 hard-coded face_left @ 100mm).
        thickness = catalogs.wall_thickness_mm.get(wall["revit_type"])
        if thickness is None:
            raise OpError("unknown_revit_type", wall["revit_type"])
        point = placement.place(
            f"face_{args['face']}",
            tuple(wall["start"]),
            tuple(wall["end"]),
            thickness,
            args["offset"],
            args["height_afl"],
        )
        self.devices[args["id"]] = {**args, "point": point}
        return args["id"]

    @staticmethod
    def _check_path(path: list[list[float]]) -> None:
        """Every segment must have positive 3D length: a zero-length Pipe.Create /
        Conduit.Create throws in Revit, so the sim rejects it the same way."""
        for a, b in zip(path, path[1:], strict=False):
            if math.dist(a, b) < 1e-6:
                raise OpError("invalid_path", f"zero-length segment at {a}")

    def _op_create_pipe(self, args: dict[str, Any], catalogs: Catalogs) -> str:
        self._require_new_id(args["id"])
        if args["pipe_type"] not in catalogs.pipe_types:
            raise OpError("unknown_revit_type", args["pipe_type"])
        self._check_path(args["path"])
        self.pipes[args["id"]] = dict(args)
        return args["id"]

    def _op_create_conduit(self, args: dict[str, Any], _c: Catalogs) -> str:
        self._require_new_id(args["id"])
        self._check_path(args["path"])
        self.conduits[args["id"]] = dict(args)
        return args["id"]

    def _op_set_parameter(self, args: dict[str, Any], catalogs: Catalogs) -> None:
        if args["param"] not in catalogs.param_allowlist:
            raise OpError("param_not_allowlisted", args["param"])
        if args["target_id"] not in self.all_ids():
            raise OpError("unknown_target", args["target_id"])
        self.parameters.setdefault(args["target_id"], {})[args["param"]] = args["value"]
        return None

    def _op_set_phase_demolished(self, args: dict[str, Any], _c: Catalogs) -> None:
        if args["target_id"] not in self.all_ids():
            raise OpError("unknown_target", args["target_id"])
        self.demolished.add(args["target_id"])
        return None

    def _guard_generated_wall(self, wall_id: str) -> dict[str, Any]:
        wall = self._wall(wall_id)
        # SI-8: elements created with phase="existing" came from Commit #0 scans;
        # delete/update are valid only for generated elements.
        if wall["phase"] == "existing":
            raise OpError("immutable_existing", wall_id)
        return wall

    def _op_delete_element(self, args: dict[str, Any], _c: Catalogs) -> None:
        target = args["target_id"]
        if target in self.walls:
            self._guard_generated_wall(target)
            del self.walls[target]
        elif target in self.families:
            del self.families[target]
        elif target in self.doors:
            del self.doors[target]
        elif target in self.windows:
            del self.windows[target]
        elif target in self.devices:
            del self.devices[target]
        elif target in self.pipes:
            del self.pipes[target]
        elif target in self.conduits:
            del self.conduits[target]
        else:
            raise OpError("unknown_target", target)
        return None

    def _op_update_wall(self, args: dict[str, Any], catalogs: Catalogs) -> None:
        wall = self._guard_generated_wall(args["id"])
        if "revit_type" in args and args["revit_type"] not in catalogs.wall_types:
            raise OpError("unknown_revit_type", args["revit_type"])
        for key in ("start", "end", "height", "revit_type"):
            if key in args:
                wall[key] = args[key]
        return None

    def _op_link_pointcloud(self, args: dict[str, Any], _c: Catalogs) -> None:
        self.pointclouds.append(args["blob_ref"])
        return None

    def _op_run_interference_check(self, args: dict[str, Any], _c: Catalogs) -> None:
        boxes: list[tuple[str, float, float, float, float]] = []
        for fid, fam in self.families.items():
            cx, cy = fam["center"]
            w, d = fam["footprint"]
            rad = math.radians(fam["rotation_deg"])
            # AABB of the rotated oriented rectangle (D1 footprint semantics)
            hx = (abs(w * math.cos(rad)) + abs(d * math.sin(rad))) / 2
            hy = (abs(w * math.sin(rad)) + abs(d * math.cos(rad))) / 2
            boxes.append((fid, cx - hx, cy - hy, cx + hx, cy + hy))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                    raise OpError("interference", f"{a[0]}~{b[0]}")
        return None
