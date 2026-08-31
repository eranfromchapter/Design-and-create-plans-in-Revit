"""Test-side envelope signing: the same fixed seed as the conformance manifest, so
executor tests run without a gateway. Mirrors the gateway's canonicalize-once rule
for this value class (ints + ASCII strings)."""

from __future__ import annotations

import json
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SEED = bytes.fromhex("f00dfeed" * 8)
KEY = Ed25519PrivateKey.from_private_bytes(SEED)
PUBLIC_HEX = KEY.public_key().public_bytes_raw().hex()

PROJECT_ID = "6f1c2a3e-9b4d-4c5e-8f70-123456789abc"
WORKSTATION_ID = "ws-design-01"


def make_body(
    seq: int,
    ops: list[dict[str, Any]],
    issued_at: str = "2026-01-01T00:00:00Z",
    ttl_s: int = 600,
    **overrides: Any,
) -> dict[str, Any]:
    body = {
        "envelope_id": f"0b5e7a1c-2d3f-4a5b-8c9d-0e1f2a3b4{seq:03d}",
        "project_id": PROJECT_ID,
        "workstation_id": WORKSTATION_ID,
        "seq": seq,
        "issued_at": issued_at,
        "ttl_s": ttl_s,
        "ops": ops,
    }
    body.update(overrides)
    return body


def sign_envelope(body: dict[str, Any]) -> dict[str, str]:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"payload": payload, "sig": KEY.sign(payload.encode("utf-8")).hex()}


def wall_op(
    i: int, y: float = 0.0, revit_type: str = "CHPT_Partition_92mm_PLACEHOLDER"
) -> dict[str, Any]:
    return {
        "op": "create_wall",
        "args": {
            "id": f"W-{i:03d}",
            "start": [0, y],
            "end": [4000, y],
            "revit_type": revit_type,
            "height": 2700,
            "phase": "new",
        },
    }
