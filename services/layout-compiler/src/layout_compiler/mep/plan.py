"""plan_mep(): the Phase 6 MEP agent's orchestration (docs/PHASE6_DESIGN.md §1.1).
Inputs resolution -> P-1..P-4 -> E-1..E-3 -> E-4 -> registry-validated ops ->
sim-replay preflight + review-card SVGs -> MepPlan. Wall clock lives ONLY here
(MEP_TIME_LIMIT_S at the request boundary; the deadline callback is threaded into
every rule so the time limit interrupts the solver itself — SI-6)."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from chapter_contracts.generated.chapter_layout import ChapterLayout
from revit_sim.model import OpError

from layout_compiler.mep.constants import MEP_TIME_LIMIT_S
from layout_compiler.mep.electrical import plan_electrical
from layout_compiler.mep.inputs import MepError, resolve_inputs
from layout_compiler.mep.ops import conduit_ops, device_ops, pipe_ops, validate_ops
from layout_compiler.mep.plumbing import plan_plumbing
from layout_compiler.mep.routing import route_home_runs
from layout_compiler.replay import render_mep_svgs

BLOCKING_CODES = frozenset(
    {
        "panel_missing",
        "levels_missing",
        "levels_inconsistent",
        "plenum_too_shallow",
        "no_wet_wall_candidate",
        "stacks_exceeded",
        "p1_iterations_exceeded",
        "outlet_spacing_invalid",
        "fixture_kind_unknown",
    }
)


@dataclass(frozen=True)
class MepOptions:
    project_id: str


def plan_mep(
    commit0_layout: dict[str, Any],
    commit1_layout: dict[str, Any],
    commit1_ops: list[dict[str, Any]],
    interior_ops: list[dict[str, Any]],
    furnished_layout: dict[str, Any],
    placer_wall_ids: dict[str, str] | None,
    confirmations: dict[str, Any] | None,
    opts: MepOptions,
) -> dict[str, Any]:
    """Returns the MepPlan (the `mep_plan` review content minus gateway-stamped keys).
    Raises MepError on every failure path: commit1_layout_invalid,
    furnished_layout_invalid, panel_not_on_wall, mep_timeout, mep_internal."""
    started = time.monotonic()
    deadline = started + MEP_TIME_LIMIT_S

    def deadline_check() -> None:
        if time.monotonic() > deadline:
            raise MepError("mep_timeout", f"plan-mep exceeded {MEP_TIME_LIMIT_S:.0f}s")

    for name, layout in (
        ("commit1_layout", commit1_layout),
        ("furnished_layout", furnished_layout),
    ):
        try:
            ChapterLayout.model_validate(layout)
        except Exception as err:
            raise MepError(f"{name}_invalid", f"{name} failed the contract: {err}") from err
    del opts  # project identity rides in the layouts' meta; kept for symmetry with compile/furnish

    inputs = resolve_inputs(
        furnished_layout, commit0_layout, confirmations, placer_wall_ids, deadline_check
    )
    deadline_check()
    plumbing = plan_plumbing(inputs, deadline_check)
    zones = [(s.wall_id, s.offset) for s in plumbing.stacks]
    electrical = plan_electrical(inputs, zones, deadline_check)
    routing = route_home_runs(inputs, electrical.devices, zones, deadline_check)
    deadline_check()

    ops = (
        pipe_ops(plumbing.stacks, plumbing.segments, inputs)
        + device_ops(electrical.devices)
        + conduit_ops(routing.drops, routing.trunks, inputs)
    )
    validate_ops(ops)
    try:
        svgs = render_mep_svgs(commit0_layout, commit1_ops, interior_ops, ops)
    except OpError as err:  # preflight: the executor would reject an op
        raise MepError("mep_internal", f"sim preflight rejected {err.code}: {err.message}") from err

    items = [*inputs.items, *plumbing.items, *electrical.items, *routing.items]
    review_items = [i.to_dict() for i in items]
    for item in review_items:
        item["severity"] = "blocking" if item["code"] in BLOCKING_CODES else "info"
    blocking = sorted({i["code"] for i in review_items if i["severity"] == "blocking"})
    kinds = Counter(d.kind for d in electrical.devices)
    counts = {
        "devices": len(electrical.devices),
        "receptacle": kinds.get("receptacle", 0),
        "gfci": kinds.get("gfci", 0),
        "switch": kinds.get("switch", 0),
        "receptacle_240": kinds.get("receptacle_240", 0),
        "pipes": len(plumbing.stacks) + len(plumbing.segments),
        "stacks": len(plumbing.stacks),
        "conduits": len(routing.drops) + len(routing.trunks),
        "review_items": len(review_items),
        "blocking": len(blocking),
        "extensions": {
            "appliance": sum(1 for d in electrical.devices if d.rule == "appliance"),
        },
    }
    return {
        "layout": inputs.layout,
        "inputs": inputs.summary(),
        "stacks": [s.to_dict() for s in plumbing.stacks],
        "branches": [s.to_dict() for s in plumbing.segments],
        "fixture_routes": plumbing.fixture_routes,
        "devices": [d.to_dict() for d in electrical.devices],
        "home_runs": [h.to_dict() for h in routing.home_runs],
        "ops": ops,
        "review_items": review_items,
        "blocking": blocking,
        "svgs": svgs,
        "diagnostics": {
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "counters": {**plumbing.counters, **electrical.counters, **routing.counters},
        },
        "counts": counts,
    }
