"""Session-scoped golden model (the Phase 6 chain replayed through the real SimModel) and its
rasterised views — the slow part, computed once per test session."""

from __future__ import annotations

import pytest
from revit_sim.render.png import rasterize

from aidm_bridge.golden_render import PX, VIEWS, golden_chain_and_model, golden_svgs


@pytest.fixture(scope="session")
def golden():
    chain, merged, model = golden_chain_and_model()
    return {"chain": chain, "merged": merged, "model": model, "svgs": golden_svgs(model)}


@pytest.fixture(scope="session")
def golden_pngs(golden):
    return {name: rasterize(golden["svgs"][name], PX) for name, _ in VIEWS}
