"""Sim replay: the frozen layout and the diff ops re-executed through the REAL
revit-sim model + canonical renderer (architect pass verdict #1). Two jobs:

- preflight: anything the sim executor would reject (unknown catalog type,
  duplicate id, out-of-host offset) fails compile HERE, before a human ever
  sees the review card;
- review-card SVGs: existing vs new rendered by the renderer of record, so the
  approved card's new SVG is byte-identical to the post-commit sim export
  (test_replay pins Commit #0 replay against fixtures/goldens/phase2_2br.svg).

The existing-model construction mirrors the gateway's opsFromScanLayout
(services/gateway/src/scan/ops.ts) minus create_level/link_pointcloud, which
the renderer ignores; heights come from the frozen snapshot (the confirmed
ceiling is already applied there)."""

from __future__ import annotations

from functools import cache
from typing import Any

from revit_sim.model import Catalogs, SimModel
from revit_sim.render.svg import render_plan

from layout_compiler.architectural import WALL_FLAG_KEYS


@cache
def _catalogs() -> Catalogs:
    return Catalogs.load()


def sim_model_from_layout(layout: dict[str, Any]) -> SimModel:
    """Replay a frozen phase="existing" ChapterLayout into a SimModel."""
    model = SimModel()
    catalogs = _catalogs()
    for wall in sorted(layout["walls"], key=lambda w: w["id"]):
        args: dict[str, Any] = {
            "id": wall["id"],
            "start": wall["start"],
            "end": wall["end"],
            "revit_type": wall["revit_type"],
            "height": wall["height"],
            "phase": "existing",
        }
        flags = {k: wall[k] for k in WALL_FLAG_KEYS if k in wall}
        if flags:
            args["flags"] = flags
        model.apply("create_wall", args, catalogs)
    for door in sorted(layout["doors"], key=lambda d: d["id"]):
        model.apply(
            "create_door",
            {
                "id": door["id"],
                "host_wall_id": door["host_wall_id"],
                "offset": door["offset"],
                "revit_type": door["revit_type"],
                "width": door["width"],
                "height": door["height"],
                "swing": door.get("swing", "L"),
            },
            catalogs,
        )
    for window in sorted(layout["windows"], key=lambda w: w["id"]):
        model.apply(
            "create_window",
            {
                "id": window["id"],
                "host_wall_id": window["host_wall_id"],
                "offset": window["offset"],
                "sill_height": window["sill_height"],
                "revit_type": window["revit_type"],
                "width": window["width"],
                "height": window["height"],
            },
            catalogs,
        )
    return model


def render_review_svgs(
    existing_layout: dict[str, Any], ops: list[dict[str, Any]]
) -> dict[str, str]:
    """{"existing": svg, "new": svg} — the new model is existing + ops applied.
    Raises revit_sim.model.OpError when the sim would reject an op (preflight)."""
    existing = sim_model_from_layout(existing_layout)
    new = existing.clone()
    for op in ops:
        new.apply(op["op"], op["args"], _catalogs())
    return {"existing": render_plan(existing), "new": render_plan(new)}


def render_furnish_svgs(
    commit0_layout: dict[str, Any],
    commit1_ops: list[dict[str, Any]],
    place_ops: list[dict[str, Any]],
) -> dict[str, str]:
    """{"commit1": svg, "furnished": svg} for the interior review card: the
    Commit #0 replay plus the approved Commit #1 ops (demolished elements
    dashed) is post-Commit-#1 reality; the furnished view adds the place ops.
    Same canonical renderer, so the furnished card equals what the sim will
    show after Commit #2's interior half — modulo the MEP layers Phase 6 adds.
    Raises revit_sim.model.OpError when the sim would reject an op (preflight)."""
    model = sim_model_from_layout(commit0_layout)
    for op in commit1_ops:
        model.apply(op["op"], op["args"], _catalogs())
    furnished = model.clone()
    for op in place_ops:
        furnished.apply(op["op"], op["args"], _catalogs())
    return {"commit1": render_plan(model), "furnished": render_plan(furnished)}
