"""Cross-language conformance: this exact suite (same manifest) runs in TS and C# too."""

import json
from pathlib import Path

import pytest

from chapter_contracts import verify_envelope

MANIFEST = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "conformance" / "manifest.json").read_text()
)


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=[c["name"] for c in MANIFEST["cases"]])
def test_conformance_case(case):
    result = verify_envelope(
        case["envelope"],
        MANIFEST["public_key_hex"],
        case["verify_at"],
        case["last_committed_seq"],
    )
    assert result.status == case["expect"]
    if result.status == "rejected":
        assert result.reason == case["reason"]
