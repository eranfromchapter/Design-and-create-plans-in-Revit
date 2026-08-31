import copy
import json
from pathlib import Path

import pytest
import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from chapter_contracts.generated.chapter_layout import ChapterLayout

REPO = Path(__file__).resolve().parents[4]
SCHEMA = json.loads(
    (REPO / "packages" / "contracts" / "schemas" / "chapter-layout.v2.3.json").read_text()
)
FIXTURE = json.loads((REPO / "fixtures" / "layouts" / "minimal.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def test_minimal_fixture_validates_jsonschema():
    errors = list(VALIDATOR.iter_errors(FIXTURE))
    assert errors == []


def test_minimal_fixture_parses_pydantic():
    layout = ChapterLayout.model_validate(FIXTURE)
    assert layout.meta.schema_version == "2.3"
    assert len(layout.walls) == 4


def test_canonical_roundtrip_byte_identical():
    layout = ChapterLayout.model_validate(FIXTURE)
    dumped = layout.model_dump(mode="json", exclude_unset=True)
    assert rfc8785.dumps(dumped) == rfc8785.dumps(FIXTURE)


def test_rejects_misspelled_flag():
    bad = copy.deepcopy(FIXTURE)
    bad["walls"][0]["is_load_baering"] = True
    assert not VALIDATOR.is_valid(bad)
    with pytest.raises(ValidationError):
        ChapterLayout.model_validate(bad)


def test_rejects_zero_footprint():
    bad = copy.deepcopy(FIXTURE)
    bad["furniture"][0]["items"][0]["footprint"] = [2200, 0]
    assert not VALIDATOR.is_valid(bad)


def test_pointcloud_requires_levels():
    bad = copy.deepcopy(FIXTURE)
    bad["meta"]["scan"] = {"source": "polycam", "capture": "pointcloud"}
    del bad["meta"]["levels"]
    assert not VALIDATOR.is_valid(bad)
