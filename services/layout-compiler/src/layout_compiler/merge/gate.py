"""merge(): the Phase 6 merge gate (docs/PHASE6_DESIGN.md §4.5, PIN-28..31) —
Interior + MEP branch deltas -> Phase A sweep -> lower-priority re-plans under the
shared Phase A + Phase B budget (`iterations_used` re-plan rounds, a round may start
iff < MERGE_BUDGET) -> merged Commit #2 ops + clash report + card SVGs. Stateless:
the gateway passes iterations_used / prior_actions / clash_pairs and this function
replays them deterministically. Wall clock lives only here (MERGE_TIME_LIMIT_S)."""

from __future__ import annotations

import copy
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from chapter_contracts.generated.chapter_layout import ChapterLayout
from revit_sim.model import OpError

from layout_compiler.mep.constants import MERGE_BUDGET, MERGE_TIME_LIMIT_S
from layout_compiler.mep.inputs import MepError, resolve_inputs
from layout_compiler.mep.ops import validate_ops
from layout_compiler.merge.clash import phase_a
from layout_compiler.merge.replan import MergeError, MergeState, apply_pair, replay_actions
from layout_compiler.replay import render_merge_svgs
from layout_compiler.validator import validate_layout

INTERFERENCE_CHECK = {"op": "run_interference_check", "args": {"scope": "last_commit"}}


@dataclass(frozen=True)
class MergeOptions:
    project_id: str


def merge(
    commit0_layout: dict[str, Any],
    commit1_ops: list[dict[str, Any]],
    interior: dict[str, Any],
    mep: dict[str, Any],
    iterations_used: int,
    iteration: int,
    prior_actions: list[dict[str, Any]],
    clash_pairs: list[dict[str, Any]],
    opts: MergeOptions,
) -> dict[str, Any]:
    """interior = {review_id, content_hash, ops, layout}; mep = {review_id,
    content_hash, plan (MepPlan)}. Returns the MergeResult; raises MergeError with
    codes interior_layout_invalid | clash_pair_unknown | merge_timeout |
    merge_internal."""
    started = time.monotonic()
    deadline = started + MERGE_TIME_LIMIT_S

    def deadline_check() -> None:
        if time.monotonic() > deadline:
            raise MergeError("merge_timeout", f"merge exceeded {MERGE_TIME_LIMIT_S:.0f}s")

    del opts
    try:
        ChapterLayout.model_validate(interior["layout"])
    except Exception as err:
        raise MergeError("interior_layout_invalid", str(err)) from err
    plan = mep["plan"]
    if plan.get("blocking"):
        raise MergeError("merge_internal", f"mep plan has blocking items: {plan['blocking']}")
    try:
        inputs = resolve_inputs(
            plan["layout"], commit0_layout, None, plan["inputs"].get("host_walls"), deadline_check
        )
    except MepError as err:
        raise MergeError("merge_internal", f"mep inputs: {err.code}") from err
    if inputs.blocking():
        raise MergeError("merge_internal", f"mep inputs blocking: {inputs.blocking()}")

    state = MergeState(
        layout=copy.deepcopy(plan["layout"]),
        interior_ops=copy.deepcopy(interior["ops"]),
        mep_ops=copy.deepcopy(plan["ops"]),
        branch_fixtures={b["id"]: list(b["fixture_ids"]) for b in plan.get("branches", [])},
        devices_meta={d["id"]: d for d in plan.get("devices", [])},
        stacks_meta=[
            {"id": s["id"], "wall_id": s["wall_id"], "offset": s["offset"]}
            for s in plan.get("stacks", [])
        ],
        inputs=inputs,
        segment_stack={b["id"]: b["stack_id"] for b in plan.get("branches", [])},
        refresh_inputs=lambda layout: resolve_inputs(
            layout, commit0_layout, None, plan["inputs"].get("host_walls"), deadline_check
        ),
    )
    replay_actions(state, prior_actions, deadline_check)

    used = int(iterations_used)
    actions: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    replans: list[dict[str, Any]] = []

    def report(status: str, clashes: list[Any]) -> dict[str, Any]:
        prisms = state.prisms()
        return {
            "budget": {
                "limit": MERGE_BUDGET,
                "used": used,
                "remaining": max(0, MERGE_BUDGET - used),
            },
            "phase_a": {"rounds": rounds},
            "phase_b": {"replans": replans},
            "prisms": dict(Counter(p.cls for p in prisms)),
            "open_clashes": [c.to_dict() for c in clashes],
            "status": status,
        }

    def result(
        status: str, clashes: list[Any], ops: list[dict[str, Any]], svgs: dict[str, str]
    ) -> dict[str, Any]:
        return {
            "status": status,
            "iteration": iteration,
            "iterations_used": used,
            "interior": {
                "review_id": interior["review_id"],
                "content_hash": interior["content_hash"],
                "ops_count": len(state.interior_ops),
                "ops_verbatim": state.interior_verbatim,
            },
            "mep": {
                "review_id": mep["review_id"],
                "content_hash": mep["content_hash"],
                "ops_count": len(state.mep_ops),
            },
            "layout": state.layout,
            "ops": ops,
            "actions": actions,
            "replan_deltas": state.replan_deltas,
            "dropped": list(state.dropped),
            "clash_report": report(status, clashes),
            "svgs": svgs,
            "blocked_reason": state.blocked,
            "counts": {
                "ops": len(ops),
                **dict(Counter(op["op"] for op in ops)),
            },
        }

    # ---- Phase B trigger: the executor rolled Commit #2 back with interference pairs
    if clash_pairs:
        if used >= MERGE_BUDGET:
            return result("budget_exhausted", [], [], {})
        acts = []
        for pair in sorted(clash_pairs, key=lambda p: (p["a_id"], p["b_id"])):
            acts.append(
                apply_pair(
                    state,
                    pair["a_id"],
                    pair["b_id"],
                    pair.get("kind", "hard_interference"),
                    iteration,
                    "phase_b",
                    deadline_check,
                )
            )
            if state.blocked:
                break
        actions.extend(acts)
        used += 1
        replans.append({"iteration": iteration, "pairs": list(clash_pairs), "actions": acts})
        if state.blocked:
            return result("blocked", [], [], {})

    # ---- Phase A rounds
    for _ in range(MERGE_BUDGET + 1):
        deadline_check()
        clashes = phase_a(state.prisms(), deadline_check)
        if not clashes:
            oracle = validate_layout(state.layout)
            if oracle:
                raise MergeError(
                    "merge_internal", "merged layout fails the validator: " + "; ".join(oracle[:3])
                )
            ops = [*state.interior_ops, *state.mep_ops, INTERFERENCE_CHECK]
            validate_ops(ops)
            try:
                svgs = render_merge_svgs(commit0_layout, commit1_ops, ops)
            except OpError as err:
                raise MergeError(
                    "merge_internal", f"sim preflight rejected {err.code}: {err.message}"
                ) from err
            return result("clean", [], ops, svgs)
        if used >= MERGE_BUDGET:
            return result("budget_exhausted", clashes, [], {})
        acts = []
        for c in clashes:
            acts.append(
                apply_pair(
                    state, c.a_id, c.b_id, "phase_a_overlap", iteration, "phase_a", deadline_check
                )
            )
            if state.blocked:
                break
        actions.extend(acts)
        used += 1
        rounds.append(
            {"iteration": iteration, "clashes": [c.to_dict() for c in clashes], "actions": acts}
        )
        if state.blocked:
            return result("blocked", clashes, [], {})
    return result("budget_exhausted", phase_a(state.prisms()), [], {})
