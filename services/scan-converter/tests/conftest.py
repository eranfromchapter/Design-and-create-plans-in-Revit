"""Session fixtures: the canonical 2BR at each unit variant, built in memory from
the same spec module the committed DXF came from."""

from __future__ import annotations

import pytest
from helpers import PROJECT_ID, doc_bytes

from scan_converter.dxf_build import build_fixture_doc
from scan_converter.lane_a import ConvertOptions


@pytest.fixture(scope="session")
def fixture_mm_bytes() -> bytes:
    return doc_bytes(build_fixture_doc())


@pytest.fixture(scope="session")
def fixture_inch_bytes() -> bytes:
    return doc_bytes(build_fixture_doc(insunits=1, scale=1 / 25.4))


@pytest.fixture(scope="session")
def fixture_unitless_bytes() -> bytes:
    """$INSUNITS=0 with mm-scale coordinates: heuristic + confirmation path."""
    return doc_bytes(build_fixture_doc(insunits=0, scale=1.0))


@pytest.fixture()
def opts() -> ConvertOptions:
    return ConvertOptions(project_id=PROJECT_ID)
