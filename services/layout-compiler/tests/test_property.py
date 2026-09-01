"""Hypothesis properties, honestly framed: (1) the validator is TOTAL — for
arbitrarily mutated layout documents it returns a sorted list of strings and
never raises, so nothing can be silently committed; (2) the Part G identity
tolerance is exactly EPSILON_MM on kept elements — bigger perturbations are
rejected, smaller ones accepted, never reinterpreted as demolish+create."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from layout_compiler.architectural import EPSILON_MM, DiffError, diff_layouts
from layout_compiler.golden_4br import emission, frozen_layout
from layout_compiler.validator import validate_layout

FROZEN = frozen_layout()
GOLDEN = emission()
META = {
    "project_id": "1f6b3c58-7a2d-4e90-9c41-2b8f5d6a7e01",
    "level": "Level 1",
    "units": "mm",
    "origin": "revit_internal_origin",
    "schema_version": "2.3",
    "brief_version": 1,
    "phase": "new",
}

JUNK = st.sampled_from([None, "", "W-9999", -1, 10**9, [], {}, 3.5, True])
GROUPS = st.sampled_from(["walls", "doors", "windows", "rooms"])


@settings(max_examples=60, deadline=None)
@given(
    group=GROUPS,
    index=st.integers(min_value=0, max_value=30),
    field_action=st.tuples(st.sampled_from(["delete", "junk"]), JUNK),
    data=st.data(),
)
def test_validator_is_total_under_document_mutation(group, index, field_action, data):
    layout: dict[str, Any] = {"meta": dict(META), **copy.deepcopy(GOLDEN)}
    elements = layout[group]
    element = elements[index % len(elements)]
    field = data.draw(st.sampled_from(sorted(element.keys())))
    action, junk = field_action
    if action == "delete":
        del element[field]
    else:
        element[field] = junk

    errors = validate_layout(layout, frozen=FROZEN)
    assert isinstance(errors, list)
    assert errors == sorted(errors)
    assert all(isinstance(e, str) for e in errors)
    # the verdict is total AND stable: same document, same verdict
    assert validate_layout(layout, frozen=FROZEN) == errors


@settings(max_examples=80, deadline=None)
@given(
    wall_index=st.integers(min_value=0, max_value=14),  # the 15 kept scan walls lead the list
    field=st.sampled_from(["start", "end"]),
    coord=st.integers(min_value=0, max_value=1),
    delta=st.floats(min_value=-400, max_value=400, allow_nan=False, allow_infinity=False),
)
def test_identity_epsilon_is_exactly_one_mm(wall_index, field, coord, delta):
    assume(abs(abs(delta) - EPSILON_MM) > 0.01)  # stay off the float boundary
    assume(abs(delta) > 1e-9)
    new = copy.deepcopy(GOLDEN)
    wall = new["walls"][wall_index]
    assert wall["source"] == "scan"  # the mutation targets a kept element
    wall[field][coord] += delta

    subject = {"walls": new["walls"], "doors": new["doors"], "windows": new["windows"]}
    if abs(delta) > EPSILON_MM:
        with pytest.raises(DiffError) as err:
            diff_layouts(FROZEN, subject)
        assert wall["id"] in "\n".join(err.value.violations)
    else:
        result = diff_layouts(FROZEN, subject)
        # accepted within tolerance — and never reinterpreted as demolish+create
        assert all(
            op["op"] != "set_phase_demolished" or op["args"]["target_id"] != wall["id"]
            for op in result.ops
        )
