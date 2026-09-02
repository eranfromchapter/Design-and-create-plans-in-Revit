"""The Phase 6 golden MEP chain on the golden 2BR (docs/PHASE6_DESIGN.md §8): the
confirmations the card would collect (panel + slab-to-slab — the flag-free,
riser-free chain carries neither), the injected Phase-B pair the recovery demo
replays, and the pure functions scripts/gen_golden_mep.py (the SOLE source of
golden truth — copy nothing by hand), tests/test_mep_golden.py and
scripts/demo_phase6.py share. Predicted outcome under the pinned defaults: 2 stacks
(P-001 on the bath wet wall W-004, P-002 on the kitchen wall W-026 snapped out of
D-011's span), 10 pipes, 45 devices, Phase A 0 clashes; recovery = two injected
rejects → E-001 slides 1912.5 → 1762.5 → 1612.5 and Commit #2 lands at plan 3 with
iterations_used = 2; four rejects exhaust the budget → REVIEW."""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from collections.abc import Iterator
from typing import Any

from layout_compiler.golden_4br import REPO_ROOT, frozen_layout
from layout_compiler.mep import plumbing as plumbing_mod
from layout_compiler.mep import runs as runs_mod
from layout_compiler.mep.constants import MERGE_BUDGET
from layout_compiler.mep.electrical import plan_electrical
from layout_compiler.mep.inputs import resolve_inputs
from layout_compiler.mep.plan import MepOptions, plan_mep
from layout_compiler.mep.plumbing import plan_plumbing
from layout_compiler.mep.routing import route_home_runs
from layout_compiler.merge.gate import MergeOptions, merge

PANEL = [8050.0, 5200.0]  # foyer, inside face of W-019 → panel foot (8000, 5200)
SLAB_TO_SLAB_MM = 3000.0  # h_plenum = 300 with the 2700 ceiling
CONFIRMATIONS: dict[str, Any] = {"panel": PANEL, "slab_to_slab_mm": SLAB_TO_SLAB_MM}
INJECTED_PAIR = {"a_id": "E-001", "b_id": "P-001", "kind": "hard_interference"}  # executor order
RECOVERY_REJECTS = 2  # executor rolls Commit #2 back twice → commits at plan 3
EXHAUSTION_REJECTS = MERGE_BUDGET + 1  # one more than the budget → REVIEW
EXPECTED_SHIFTS = [1762.5, 1612.5]  # E-001 offset after rejects 1 and 2 (1912.5 − 150·k)

INTERIOR_REVIEW = {"review_id": "golden-interior-plan", "content_hash": "1" * 64}
MEP_REVIEW = {"review_id": "golden-mep-plan", "content_hash": "2" * 64}

GOLDENS = REPO_ROOT / "fixtures" / "goldens"
FILES = {
    "mep_svg": GOLDENS / "phase6_2br_mep.svg",
    "mep_json": GOLDENS / "phase6_2br_mep.json",
    "clash_report": GOLDENS / "phase6_2br_clash_report.json",
    "recovery_json": GOLDENS / "phase6_2br_recovery.json",
    "recovery_svg": GOLDENS / "phase6_2br_recovery.svg",
    "gate_note": GOLDENS / "phase6_2br_gate_note.json",
}


def dumps(obj: Any) -> str:
    """The one serializer every JSON golden is written and compared with."""
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def golden_chain() -> dict[str, Any]:
    """compile (recorded) → furnish (recorded emission + real placer) on the frozen
    2BR: {brief, commit0, commit1_layout, commit1_ops, furnished, interior_ops,
    placer_wall_ids}."""
    from layout_compiler.compile import CompileOptions, compile_layout
    from layout_compiler.fixtures import FixtureLLM
    from layout_compiler.furnish import FurnishOptions, furnish_layout
    from layout_compiler.interior_fixtures import InteriorFixtureLLM

    brief = json.loads((REPO_ROOT / "fixtures" / "briefs" / "2br_golden_brief.json").read_text())
    brief["meta"]["confirmed_by_client"] = True
    project = brief["meta"]["project_id"]
    compiled = compile_layout(
        brief, frozen_layout(), CompileOptions(project_id=project), FixtureLLM()
    )
    furnished = furnish_layout(
        brief,
        frozen_layout(),
        compiled["layout"],
        compiled["ops"],
        FurnishOptions(project_id=project),
        InteriorFixtureLLM(),
    )
    return {
        "brief": brief,
        "commit0": frozen_layout(),
        "commit1_layout": compiled["layout"],
        "commit1_ops": compiled["ops"],
        "furnished": furnished["layout"],
        "interior_ops": furnished["ops"],
        "placer_wall_ids": {
            d["item_id"]: d["wall_id"]
            for d in furnished["diagnostics"]["items"]
            if d.get("wall_id")
        },
    }


def plan_golden(chain: dict[str, Any]) -> dict[str, Any]:
    return plan_mep(
        chain["commit0"],
        chain["commit1_layout"],
        chain["commit1_ops"],
        chain["interior_ops"],
        chain["furnished"],
        chain["placer_wall_ids"],
        CONFIRMATIONS,
        MepOptions(project_id=chain["brief"]["meta"]["project_id"]),
    )


def merge_golden(
    chain: dict[str, Any],
    plan: dict[str, Any],
    iterations_used: int = 0,
    iteration: int = 1,
    prior_actions: list[dict[str, Any]] | None = None,
    clash_pairs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return merge(
        chain["commit0"],
        chain["commit1_ops"],
        {**INTERIOR_REVIEW, "ops": chain["interior_ops"], "layout": chain["furnished"]},
        {**MEP_REVIEW, "plan": plan},
        iterations_used,
        iteration,
        list(prior_actions or []),
        list(clash_pairs or []),
        MergeOptions(project_id=chain["brief"]["meta"]["project_id"]),
    )


def compact_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """MepPlan minus the card SVGs and the timing diagnostics (the byte golden)."""
    return {k: v for k, v in plan.items() if k not in ("svgs", "diagnostics")}


def ops_diff(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ops whose args changed / appeared / vanished between two merged plans, by id."""
    a = {op["args"]["id"]: op for op in before if "id" in op["args"]}
    b = {op["args"]["id"]: op for op in after if "id" in op["args"]}
    diff = []
    for element_id in sorted(set(a) | set(b)):
        if a.get(element_id) != b.get(element_id):
            diff.append(
                {
                    "id": element_id,
                    "before": a.get(element_id, {}).get("args"),
                    "after": b.get(element_id, {}).get("args"),
                }
            )
    return diff


def rejected_sequence(
    chain: dict[str, Any], plan: dict[str, Any], rejects: int
) -> list[dict[str, Any]]:
    """The gateway's Phase-B loop: plan 1 is issued; the executor rejects it with
    INJECTED_PAIR `rejects` times; every rebuilt plan replays the prior actions
    (stateless merge). Returns every MergeResult in order (plan 1 first)."""
    results = [merge_golden(chain, plan)]
    prior: list[dict[str, Any]] = []
    used = 0
    for i in range(rejects):
        result = merge_golden(chain, plan, used, i + 2, prior, [INJECTED_PAIR])
        results.append(result)
        if result["status"] != "clean":
            break
        prior = prior + result["actions"]
        used = result["iterations_used"]
    return results


def recovery_golden(chain: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """phase6_2br_recovery.json: plans 2..3 of the recovery demo (actions, ops diff
    vs the previous plan, clash reports) plus the exhaustion sequence's statuses."""
    recovery = rejected_sequence(chain, plan, RECOVERY_REJECTS)
    exhaustion = rejected_sequence(chain, plan, EXHAUSTION_REJECTS)
    plans = []
    for previous, result in zip(recovery, recovery[1:], strict=False):
        plans.append(
            {
                "iteration": result["iteration"],
                "status": result["status"],
                "iterations_used": result["iterations_used"],
                "injected": [INJECTED_PAIR],
                "actions": result["actions"],
                "ops_diff": ops_diff(previous["ops"], result["ops"]),
                "clash_report": result["clash_report"],
                "counts": result["counts"],
            }
        )
    return {
        "injected_pair": INJECTED_PAIR,
        "recovery": {
            "rejects": RECOVERY_REJECTS,
            "commits_at_plan": len(recovery),
            "final_iterations_used": recovery[-1]["iterations_used"],
            "plans": plans,
        },
        "exhaustion": {
            "rejects": EXHAUSTION_REJECTS,
            "sequence": [
                {
                    "iteration": r["iteration"],
                    "status": r["status"],
                    "iterations_used": r["iterations_used"],
                    "e001_offset": next(
                        (
                            op["args"]["offset"]
                            for op in r["ops"]
                            if op["args"].get("id") == "E-001"
                        ),
                        None,
                    ),
                }
                for r in exhaustion
            ],
        },
    }


@contextlib.contextmanager
def _flag(module: Any, name: str, value: Any) -> Iterator[None]:
    """Flip one pinned switch for an alternative table, then restore it — the gate
    note shows both sides of a ⚠ PIN without touching the shipped default."""
    saved = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, saved)


def _stack_table(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": s.id,
            "wall_id": s.wall_id,
            "xy": [round(s.xy[0], 1), round(s.xy[1], 1)],
            "diameter": s.diameter,
            "fixtures": list(s.fixture_ids),
            "snapped": s.snapped,
        }
        for s in result.stacks
    ]


def gate_note(
    chain: dict[str, Any], plan: dict[str, Any], merged: dict[str, Any]
) -> dict[str, Any]:
    """phase6_2br_gate_note.json: what Eran decides at the gate — both sides of the
    ⚠ PINs that change the golden (PIN-08 P-4 length, PIN-13 stack zones vs device
    runs), the right-face devices, the extension and review-item counts."""
    inputs = resolve_inputs(
        plan["layout"], chain["commit0"], None, plan["inputs"].get("host_walls")
    )
    default_plumbing = plan_plumbing(inputs)
    with _flag(plumbing_mod, "P4_L_INCLUDES_DRAIN_LEG", True):
        leg_plumbing = plan_plumbing(inputs)
    zones = [(s.wall_id, s.offset) for s in default_plumbing.stacks]
    default_electrical = plan_electrical(inputs, zones)
    default_routing = route_home_runs(inputs, default_electrical.devices, zones)
    with _flag(runs_mod, "ZONES_BREAK_DEVICE_RUNS", True):
        zoned_electrical = plan_electrical(inputs, zones)
        zoned_routing = route_home_runs(inputs, zoned_electrical.devices, zones)

    def electrical_summary(electrical: Any, routing: Any) -> dict[str, Any]:
        return {
            "devices": len(electrical.devices),
            "kinds": dict(sorted(Counter(d.kind for d in electrical.devices).items())),
            "conduits": len(routing.drops) + len(routing.trunks),
            "review_items": dict(
                sorted(Counter(i.code for i in [*electrical.items, *routing.items]).items())
            ),
            "positions": [
                [d.id, d.host_wall_id, round(d.offset, 1), d.height_afl] for d in electrical.devices
            ],
        }

    codes = Counter(i["code"] for i in plan["review_items"])
    return {
        "pins_open": [
            "PIN-08",
            "PIN-12",
            "PIN-13",
            "PIN-16",
            "PIN-17",
            "PIN-20",
            "PIN-29",
            "PIN-30",
            "PIN-37",
        ],
        "pin_08_p4_length": {
            "default": {
                "switch": "P4_L_INCLUDES_DRAIN_LEG=False (L = along, spec-literal; Eran Q3)",
                "stacks": _stack_table(default_plumbing),
                "review_items": dict(
                    sorted(Counter(i.code for i in default_plumbing.items).items())
                ),
            },
            "alternative": {
                "switch": "P4_L_INCLUDES_DRAIN_LEG=True (L = leg + along)",
                "stacks": _stack_table(leg_plumbing),
                "review_items": dict(sorted(Counter(i.code for i in leg_plumbing.items).items())),
            },
        },
        "pin_13_stack_zones": {
            "default": {
                "switch": "ZONES_BREAK_DEVICE_RUNS=False",
                **electrical_summary(default_electrical, default_routing),
            },
            "alternative": {
                "switch": "ZONES_BREAK_DEVICE_RUNS=True",
                **electrical_summary(zoned_electrical, zoned_routing),
            },
        },
        "right_face_devices": sorted(
            op["args"]["id"]
            for op in plan["ops"]
            if op["op"] == "place_device" and op["args"]["face"] == "right"
        ),
        "extensions": plan["counts"]["extensions"],
        "review_item_codes": dict(sorted(codes.items())),
        "merge": {
            "status": merged["status"],
            "prisms": merged["clash_report"]["prisms"],
            "ops": merged["counts"]["ops"],
        },
        "catalog_asks": [
            "mep_types.json: real pipe/conduit/device families replace the _PLACEHOLDER rows",
            "clash_prisms.json: kind heights and the device box are engineering defaults",
            "a counter casework family (is_counter) — E-2 counter walls are derived from "
            "sink/DW today",
        ],
    }
