"""Envelope verification — the Python reference implementation of the D3 contract.

Order: sig (Ed25519 over received payload bytes) -> parse -> body schema -> TTL -> seq ->
op allowlist -> per-op args_schema. Mirrored by @chapter/contracts (TS) and
ChapterHub.Core (C#); the shared conformance vectors pin all three.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker

_CONTRACTS_DIR = Path(__file__).resolve().parents[3]

RejectReason = Literal[
    "bad_signature", "expired_ttl", "bad_seq", "unknown_op", "invalid_args", "schema_invalid"
]


@dataclass(frozen=True)
class VerifyResult:
    status: Literal["accepted", "rejected"]
    reason: RejectReason | None = None
    body: dict[str, Any] | None = None


@lru_cache(maxsize=1)
def _body_validator() -> Draft202012Validator:
    schema = json.loads((_CONTRACTS_DIR / "schemas" / "command-envelope.v1.json").read_text())
    body_schema = {**schema["$defs"]["EnvelopeBody"], "$defs": schema["$defs"]}
    return Draft202012Validator(body_schema, format_checker=FormatChecker())


@lru_cache(maxsize=1)
def _args_validators() -> dict[str, Draft202012Validator]:
    registry = json.loads((_CONTRACTS_DIR / "ops" / "registry.json").read_text())
    return {
        op: Draft202012Validator(entry["args_schema"], format_checker=FormatChecker())
        for op, entry in registry["ops"].items()
    }


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def verify_envelope(
    envelope: dict[str, str],
    public_key_hex: str,
    verify_at: datetime | str,
    last_committed_seq: int,
) -> VerifyResult:
    """Verify a wire envelope {payload, sig} with the per-project Ed25519 public key.

    verify_at is the injected "now"; last_committed_seq is the persisted state the
    monotonicity check runs against.
    """
    payload = envelope["payload"]
    given = envelope.get("sig", "")
    # The sig contract is 128 lowercase hex chars (D3); other spellings never reach the
    # signature check, keeping all three implementations agreed on what verifies.
    if not isinstance(given, str) or not re.fullmatch(r"[0-9a-f]{128}", given):
        return VerifyResult("rejected", "bad_signature")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(
            bytes.fromhex(given), payload.encode("utf-8")
        )
    except InvalidSignature:
        return VerifyResult("rejected", "bad_signature")

    try:
        body = json.loads(payload)
    except ValueError:
        return VerifyResult("rejected", "schema_invalid")
    if not _body_validator().is_valid(body):
        return VerifyResult("rejected", "schema_invalid")

    at = _parse_instant(verify_at) if isinstance(verify_at, str) else verify_at.astimezone(UTC)
    expires = _parse_instant(body["issued_at"]).timestamp() + body["ttl_s"]
    if at.timestamp() > expires:
        return VerifyResult("rejected", "expired_ttl")

    if body["seq"] <= last_committed_seq:
        return VerifyResult("rejected", "bad_seq")

    validators = _args_validators()
    for op in body["ops"]:
        validator = validators.get(op["op"])
        if validator is None:
            return VerifyResult("rejected", "unknown_op")
        if not validator.is_valid(op["args"]):
            return VerifyResult("rejected", "invalid_args")

    return VerifyResult("accepted", body=body)
