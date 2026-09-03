"""Catalog governance: placeholder SKUs are marked and shaped; the CSI table covers them; the
style vocabulary is normalised, unique and never suspicious."""

from aidm_bridge import guard
from aidm_bridge.catalogs import products
from aidm_bridge.csi import SURFACES, surface_of
from aidm_bridge.prompts import normalize_tag, vocabulary

FIELDS = {"sku", "manufacturer", "model", "description", "finish_tier", "csi_section", "unit"}
TIERS = {"economy", "standard", "premium", "luxury"}


def test_products_placeholders_marked_and_shaped():
    cat = products()
    assert cat["requires_human_input"] is True and cat["catalog_version"].endswith("-placeholder")
    rows = cat["skus"]
    assert len(rows) == 14
    for row in rows:
        assert set(row) == FIELDS and row["sku"].endswith("_PLACEHOLDER")
        assert row["finish_tier"] in TIERS
    mapped = [surface_of(r["csi_section"]) for r in rows]
    assert mapped.count(None) == 1  # the appliance row is deliberately unmapped
    assert set(m for m in mapped if m) == set(SURFACES)
    for tier in TIERS:
        assert any(r["finish_tier"] == tier and surface_of(r["csi_section"]) for r in rows)


def test_csi_table():
    assert surface_of("09 91 23") == "wall" and surface_of("09 30 13") == "wall"
    assert surface_of("06 41 16") == "casework" and surface_of("12 35 30") == "casework"
    assert surface_of("08 14 16") == "door" and surface_of("22 41 13") == "plumbing_fixture"
    assert surface_of("11 31 13") is None and surface_of("09") is None and surface_of("") is None
    assert surface_of("09  91  23") == "wall"  # whitespace-normalised


def test_vocabulary_normalised_unique_not_suspicious():
    tags = vocabulary()
    assert len(tags) >= 60
    for tag in tags:
        assert normalize_tag(tag) == tag
        assert not guard.is_suspicious(tag) and not guard.is_suspicious(tag.replace(" ", "_"))
    for golden_tag in ("modern", "warm minimalism", "light wood"):
        assert golden_tag in tags
