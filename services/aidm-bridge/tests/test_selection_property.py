"""Validator totality: any selection shape the server lets through yields a verdict, sorted
blocking codes, ops sorted by (target, param), ops empty iff blocking, and a stable repeat."""

import copy

from helpers import GOLDEN_LAYOUT, layout_ids
from hypothesis import given, settings
from hypothesis import strategies as st

from aidm_bridge.catalogs import catalog_version, sku_index
from aidm_bridge.selection import PLACEHOLDER_MARK, validate_selection

IDS = layout_ids(GOLDEN_LAYOUT)
ROOM_IDS = [r["id"] for r in GOLDEN_LAYOUT["rooms"]] + ["R-999"]
ELEMENT_IDS = IDS + ["D-999", "F-9999", "K-001"]
SKUS = sorted(sku_index()) + ["NOPE", "CHPT-WALL-PAINT-STD_PLACEHOLDER"]

item = st.fixed_dictionaries({"id": st.sampled_from(ELEMENT_IDS), "sku": st.sampled_from(SKUS)})
selection = st.fixed_dictionaries(
    {
        "rooms": st.lists(
            st.fixed_dictionaries(
                {
                    "room_id": st.sampled_from(ROOM_IDS),
                    "wall_sku": st.one_of(st.none(), st.sampled_from(SKUS)),
                }
            ),
            max_size=6,
        ),
        "casework": st.lists(item, max_size=3),
        "doors": st.lists(item, max_size=4),
        "plumbing_fixtures": st.lists(item, max_size=4),
        "overrides": st.lists(
            st.fixed_dictionaries(
                {
                    "target": st.sampled_from(ROOM_IDS + ELEMENT_IDS),
                    "sku": st.sampled_from(SKUS),
                    "reason": st.just("because"),
                }
            ),
            max_size=3,
        ),
    }
)


@settings(max_examples=80, deadline=None)
@given(selection, st.sampled_from(["economy", "standard", "premium", "luxury"]), st.booleans())
def test_validate_selection_is_total_under_mutation(sel, tier, allow):
    out = validate_selection(
        GOLDEN_LAYOUT, IDS, tier, catalog_version(), "ref", copy.deepcopy(sel), allow
    )
    assert set(out) == {"ops", "review_items", "blocking", "diagnostics"}
    assert out["blocking"] == sorted(set(out["blocking"]))
    keys = [(op["args"]["target_id"], op["args"]["param"]) for op in out["ops"]]
    assert keys == sorted(keys)
    assert (out["ops"] == []) or (out["blocking"] == [])
    again = validate_selection(
        GOLDEN_LAYOUT, IDS, tier, catalog_version(), "ref", copy.deepcopy(sel), allow
    )
    assert again == out
    if not allow:
        assert all(PLACEHOLDER_MARK not in str(op["args"]["value"]) for op in out["ops"])
