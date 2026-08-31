#!/usr/bin/env python3
"""Generate the cross-language signing conformance vectors.

The vectors pin verifier behavior: HMAC-SHA256 over the exact UTF-8 bytes of `payload`,
then parse, then TTL (against the case's fixed verify_at), then seq monotonicity
(against the case's last_committed_seq), then op allowlist + args validation.

The payload here is built with sorted keys / compact separators over integer-and-string
content, which coincides with RFC 8785 for this value class; the gateway (Phase 1) uses a
real JCS library. Verifiers never canonicalize — they HMAC received bytes — so these
vectors are canonicalization-agnostic by design.

Deterministic: fixed key, fixed uuids, fixed timestamps. Re-running must be a no-op.
"""
import hashlib
import hmac
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "conformance"
OUT.mkdir(parents=True, exist_ok=True)

KEY = bytes.fromhex("f00dfeed" * 8)          # 32-byte test-only key (not a secret)
WRONG_KEY = bytes.fromhex("deadbeef" * 8)

BODY = {
    "envelope_id": "0b5e7a1c-2d3f-4a5b-8c9d-0e1f2a3b4c5d",
    "project_id": "6f1c2a3e-9b4d-4c5e-8f70-123456789abc",
    "workstation_id": "ws-design-01",
    "seq": 2,
    "issued_at": "2026-01-01T00:00:00Z",
    "ttl_s": 600,
    "commit_label": "conformance",
    "ops": [
        {"op": "create_level", "args": {"name": "L1", "elevation": 0}},
        {
            "op": "create_wall",
            "args": {
                "id": "W-001",
                "start": [0, 0],
                "end": [4000, 0],
                "revit_type": "CHPT_Partition_92mm_PLACEHOLDER",
                "height": 2700,
                "phase": "new",
            },
        },
    ],
}


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign(payload: str, key: bytes) -> str:
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def envelope(body, key=KEY):
    payload = canonical(body)
    return {"payload": payload, "sig": sign(payload, key)}


valid = envelope(BODY)

tampered = dict(valid)
tampered["payload"] = valid["payload"].replace("ws-design-01", "ws-design-02", 1)

wrong_key = {"payload": valid["payload"], "sig": sign(valid["payload"], WRONG_KEY)}

unknown_op_body = {**BODY, "ops": [{"op": "drop_all_walls", "args": {}}]}
invalid_args_body = {**BODY, "ops": [{"op": "create_level", "args": {"name": "L1"}}]}

# Parse/schema-stage and sig-format vectors: these pin exactly the edges where
# independent implementations drift (crash paths, locale-dependent date parsing,
# case-insensitive hex decoders, null members that pass presence-only checks).
not_json_payload = "{this is not json"
malformed = {"payload": not_json_payload, "sig": sign(not_json_payload, KEY)}
no_workstation = envelope({k: v for k, v in BODY.items() if k != "workstation_id"})
null_ops = envelope({**BODY, "ops": None})
empty_ops = envelope({**BODY, "ops": []})
args_not_object = envelope({**BODY, "ops": [{"op": "create_level", "args": 42}]})
bad_issued_at = envelope({**BODY, "issued_at": "2026-01-01"})
uppercase_sig = {"payload": valid["payload"], "sig": valid["sig"].upper()}
non_hex_sig = {"payload": valid["payload"], "sig": "zz" * 32}
non_ascii_sig = {"payload": valid["payload"], "sig": "café" + valid["sig"][4:]}

manifest = {
    "description": "Signing/verification conformance vectors. Every implementation (TS, Python, C# Core) must produce these exact outcomes. verify_at is the injected 'now'; last_committed_seq is the persisted state the seq check runs against.",
    "key_hex": KEY.hex(),
    "cases": [
        {
            "name": "valid",
            "envelope": valid,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "accepted",
        },
        {
            "name": "expired_ttl",
            "envelope": valid,
            "verify_at": "2026-01-01T00:20:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "expired_ttl",
        },
        {
            "name": "tampered_payload",
            "envelope": tampered,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "bad_signature",
        },
        {
            "name": "wrong_key",
            "envelope": wrong_key,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "bad_signature",
        },
        {
            "name": "replayed_seq",
            "envelope": valid,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 2,
            "expect": "rejected",
            "reason": "bad_seq",
        },
        {
            "name": "unknown_op",
            "envelope": envelope(unknown_op_body),
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "unknown_op",
        },
        {
            "name": "invalid_args",
            "envelope": envelope(invalid_args_body),
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "invalid_args",
        },
        {
            "name": "ttl_boundary_accept",
            "envelope": valid,
            "verify_at": "2026-01-01T00:10:00Z",
            "last_committed_seq": 1,
            "expect": "accepted",
        },
        {
            "name": "ttl_boundary_plus_one_second",
            "envelope": valid,
            "verify_at": "2026-01-01T00:10:01Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "expired_ttl",
        },
        {
            "name": "malformed_payload_valid_sig",
            "envelope": malformed,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "schema_invalid",
        },
        {
            "name": "missing_workstation_id",
            "envelope": no_workstation,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "schema_invalid",
        },
        {
            "name": "null_ops",
            "envelope": null_ops,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "schema_invalid",
        },
        {
            "name": "empty_ops",
            "envelope": empty_ops,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "schema_invalid",
        },
        {
            "name": "args_not_an_object",
            "envelope": args_not_object,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "schema_invalid",
        },
        {
            "name": "bad_issued_at_date_only",
            "envelope": bad_issued_at,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "schema_invalid",
        },
        {
            "name": "uppercase_hex_sig",
            "envelope": uppercase_sig,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "bad_signature",
        },
        {
            "name": "non_hex_sig",
            "envelope": non_hex_sig,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "bad_signature",
        },
        {
            "name": "non_ascii_sig",
            "envelope": non_ascii_sig,
            "verify_at": "2026-01-01T00:05:00Z",
            "last_committed_seq": 1,
            "expect": "rejected",
            "reason": "bad_signature",
        },
    ],
}

path = OUT / "manifest.json"
path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {path} ({len(manifest['cases'])} cases)")
