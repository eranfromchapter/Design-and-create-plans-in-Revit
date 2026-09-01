"""Architectural agent (Part G): diff the compiled phase="new" layout against
the FROZEN Commit #0 snapshot under the identity spec, then emit the op list.

The identity spec is the strictest safety property in the plan:
- every frozen element the new layout keeps must match its frozen counterpart
  within EPSILON_MM on mm fields and EXACTLY on everything else (absent==absent
  for flags) — a moved or mutated existing element is REJECTED before any
  repair retry, never reinterpreted as demolish+create;
- demising / load-bearing / exterior walls are IMMUTABLE: omitting one is
  rejected, not demolished;
- renumbering is rejected: a frozen element absent from the new layout whose
  geometry reappears under a fresh id is a mutation, not new construction;
- a fresh-id wall claiming source="scan" is provenance laundering — rejected;
- risers are existing building services: passed through unchanged, never
  demolished, never invented;
- an existing element legitimately omitted is demolished BY PHASING
  (set_phase_demolished), never delete_element (SI-8).

Op order is deterministic: demolition first (doors, windows, walls — openings
before their hosts, id-sorted within each group), then creation (walls, doors,
windows — hosts before openings, id-sorted). The gateway re-validates every op
against the registry before signing; this module's output must always pass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EPSILON_MM = 1.0  # Part G identity tolerance on kept existing elements

IMMUTABLE_FLAGS = ("is_demising", "is_load_bearing", "is_exterior")
WALL_FLAG_KEYS = ("is_exterior", "is_load_bearing", "is_demising", "is_wet_wall", "fire_rating_hr")

_PT_FIELDS: dict[str, tuple[str, ...]] = {"walls": ("start", "end"), "doors": (), "windows": ()}
_MM_FIELDS: dict[str, tuple[str, ...]] = {
    "walls": ("height", "as_built_thickness"),
    "doors": ("offset", "width", "height"),
    "windows": ("offset", "width", "height", "sill_height"),
}


class DiffError(Exception):
    """The new layout mutates frozen reality; rejected before any repair."""

    def __init__(self, violations: list[str]):
        self.code = "identity_violation"
        self.violations = sorted(violations)
        super().__init__("identity_violation: " + "; ".join(self.violations))


@dataclass(frozen=True)
class DiffResult:
    ops: list[dict[str, Any]]
    demolition: list[dict[str, str]]  # review-card list, same order as the demolition ops


def _close(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= EPSILON_MM


def _pt_close(a: list[float], b: list[float]) -> bool:
    return _close(a[0], b[0]) and _close(a[1], b[1])


def _kept_violations(kind: str, frozen_el: dict[str, Any], new_el: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in sorted((set(frozen_el) | set(new_el)) - {"id"}):
        if key not in frozen_el or key not in new_el:
            side = "adds" if key not in frozen_el else "drops"
            out.append(f"{kind}.{frozen_el['id']}: kept existing element {side} field {key!r}")
            continue
        f, n = frozen_el[key], new_el[key]
        if key in _PT_FIELDS[kind]:
            ok = _pt_close(f, n)
        elif key in _MM_FIELDS[kind]:
            ok = _close(f, n)
        else:
            ok = f == n
        if not ok:
            out.append(
                f"{kind}.{frozen_el['id']}: kept existing element differs on {key!r} "
                f"({f!r} -> {n!r}); existing elements must be copied verbatim "
                f"(mm fields within {EPSILON_MM}mm)"
            )
    return out


def _same_wall_geometry(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (_pt_close(a["start"], b["start"]) and _pt_close(a["end"], b["end"])) or (
        _pt_close(a["start"], b["end"]) and _pt_close(a["end"], b["start"])
    )


def _same_opening_position(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["host_wall_id"] == b["host_wall_id"] and _close(a["offset"], b["offset"])


def diff_layouts(frozen: dict[str, Any], new: dict[str, Any]) -> DiffResult:
    """Both inputs are schema-valid ChapterLayout dicts (the pipeline runs the
    validator first); only walls/doors/windows participate in the diff — rooms
    and furniture are planning artifacts, not committed elements (Phase 5)."""
    violations: list[str] = []
    frozen_by = {k: {e["id"]: e for e in frozen[k]} for k in ("walls", "doors", "windows")}
    new_by = {k: {e["id"]: e for e in new[k]} for k in ("walls", "doors", "windows")}

    for kind in ("walls", "doors", "windows"):
        for el_id, frozen_el in frozen_by[kind].items():
            if el_id in new_by[kind]:
                violations += _kept_violations(kind, frozen_el, new_by[kind][el_id])

    for el_id, wall in frozen_by["walls"].items():
        if el_id in new_by["walls"]:
            continue
        immutable = [flag for flag in IMMUTABLE_FLAGS if wall.get(flag)]
        if immutable:
            violations.append(
                f"walls.{el_id}: immutable existing wall ({', '.join(immutable)}) is missing "
                "from the new layout — demising/load-bearing/exterior walls cannot be demolished"
            )

    renumber_probes = (
        ("walls", _same_wall_geometry),
        ("doors", _same_opening_position),
        ("windows", _same_opening_position),
    )
    for kind, same_place in renumber_probes:
        for el_id, frozen_el in frozen_by[kind].items():
            if el_id in new_by[kind]:
                continue
            for new_id, new_el in new_by[kind].items():
                if new_id not in frozen_by[kind] and same_place(frozen_el, new_el):
                    violations.append(
                        f"{kind}.{el_id}: existing element reappears as {new_id} — never "
                        "renumber existing ids; keep the original id"
                    )

    for el_id, wall in new_by["walls"].items():
        if el_id not in frozen_by["walls"] and wall.get("source") != "generated":
            violations.append(
                f'walls.{el_id}: new wall must have source="generated" '
                f"(got {wall.get('source')!r}) — scan provenance is reserved for frozen elements"
            )

    frozen_risers = {r["id"]: r for r in frozen.get("risers", [])}
    new_risers = {r["id"]: r for r in new.get("risers", [])}
    for riser_id, frozen_riser in frozen_risers.items():
        kept = new_risers.get(riser_id)
        if kept is None:
            violations.append(
                f"risers.{riser_id}: existing riser missing — risers pass through unchanged"
            )
        elif frozen_riser["type"] != kept["type"] or not _pt_close(
            frozen_riser["center"], kept["center"]
        ):
            violations.append(f"risers.{riser_id}: riser mutated — risers pass through unchanged")
    for riser_id in new_risers:
        if riser_id not in frozen_risers:
            violations.append(
                f"risers.{riser_id}: new riser invented — risers are existing building "
                "services, never generated"
            )

    if violations:
        raise DiffError(violations)

    ops: list[dict[str, Any]] = []
    demolition: list[dict[str, str]] = []
    for kind, key in (("door", "doors"), ("window", "windows"), ("wall", "walls")):
        for el_id in sorted(set(frozen_by[key]) - set(new_by[key])):
            ops.append({"op": "set_phase_demolished", "args": {"target_id": el_id}})
            demolition.append({"kind": kind, "id": el_id})

    for el_id in sorted(set(new_by["walls"]) - set(frozen_by["walls"])):
        wall = new_by["walls"][el_id]
        args: dict[str, Any] = {
            "id": wall["id"],
            "start": wall["start"],
            "end": wall["end"],
            "revit_type": wall["revit_type"],
            "height": wall["height"],
            "phase": "new",
        }
        flags = {k: wall[k] for k in WALL_FLAG_KEYS if k in wall}
        if flags:
            args["flags"] = flags
        ops.append({"op": "create_wall", "args": args})
    for el_id in sorted(set(new_by["doors"]) - set(frozen_by["doors"])):
        door = new_by["doors"][el_id]
        ops.append(
            {
                "op": "create_door",
                "args": {
                    "id": door["id"],
                    "host_wall_id": door["host_wall_id"],
                    "offset": door["offset"],
                    "revit_type": door["revit_type"],
                    "width": door["width"],
                    "height": door["height"],
                    "swing": door.get("swing", "L"),
                },
            }
        )
    for el_id in sorted(set(new_by["windows"]) - set(frozen_by["windows"])):
        window = new_by["windows"][el_id]
        ops.append(
            {
                "op": "create_window",
                "args": {
                    "id": window["id"],
                    "host_wall_id": window["host_wall_id"],
                    "offset": window["offset"],
                    "sill_height": window["sill_height"],
                    "revit_type": window["revit_type"],
                    "width": window["width"],
                    "height": window["height"],
                },
            }
        )
    return DiffResult(ops=ops, demolition=demolition)
