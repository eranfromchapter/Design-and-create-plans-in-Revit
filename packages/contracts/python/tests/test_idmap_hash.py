import json
from pathlib import Path

import pytest

from chapter_contracts import id_map_hash

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "idmap" / "hash_cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_id_map_hash_case(case):
    assert id_map_hash(case["entries"]) == case["expected_hash"]
