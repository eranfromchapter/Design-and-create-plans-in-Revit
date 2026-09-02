"""SI-6 / determinism guards for the MEP agent: no RNG, no clock, no environment
reads inside the rules (only plan.py owns the wall clock); the deadline callback
reaches the solver loops, not just the stage boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from mep_helpers import CONFIRMATIONS, commit0_for, two_baths

from layout_compiler.mep.electrical import plan_electrical
from layout_compiler.mep.inputs import MepError, resolve_inputs
from layout_compiler.mep.plumbing import plan_plumbing
from layout_compiler.mep.routing import route_home_runs

MEP_SRC = Path(__file__).resolve().parents[1] / "src" / "layout_compiler" / "mep"
FORBIDDEN_MODULES = {"random", "time", "datetime", "os", "secrets", "uuid"}


def test_rules_import_no_rng_clock_or_environment():
    offenders = []
    for path in sorted(MEP_SRC.glob("*.py")):
        if path.name == "plan.py":  # the request boundary owns the wall clock
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in FORBIDDEN_MODULES:
                    offenders.append(f"{path.name}:{node.lineno}:{name}")
    assert offenders == [], offenders


def test_plan_py_touches_only_monotonic_time():
    tree = ast.parse((MEP_SRC / "plan.py").read_text())
    calls = {
        f"{n.func.value.id}.{n.func.attr}"
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "time"
    }
    assert calls == {"time.monotonic"}


def test_deadline_callback_interrupts_every_stage():
    layout = two_baths()

    class Tripwire(Exception):
        pass

    def trip():
        raise Tripwire()

    with pytest.raises(Tripwire):
        resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS, {}, trip)
    inputs = resolve_inputs(layout, commit0_for(layout), CONFIRMATIONS, {})
    with pytest.raises(Tripwire):
        plan_plumbing(inputs, trip)
    with pytest.raises(Tripwire):
        plan_electrical(inputs, [], trip)
    devices = plan_electrical(inputs, []).devices
    calls = []

    def count():
        calls.append(1)

    route_home_runs(inputs, devices, [], count)
    assert calls, "Dijkstra must poll the deadline"


def test_mep_error_carries_a_code():
    err = MepError("x_code", "why")
    assert (err.code, err.message, str(err)) == ("x_code", "why", "x_code: why")
