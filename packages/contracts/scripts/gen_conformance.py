# /// script
# requires-python = ">=3.12"
# dependencies = ["cryptography==50.0.1"]
# ///
"""Generate the cross-language signing conformance vectors and the id-map hash cases.

Run via `uv run packages/contracts/scripts/gen_conformance.py` (PEP 723 script — uv resolves
the pinned `cryptography` hermetically). Deterministic: Ed25519 (RFC 8032) signing has no
nonce, keys derive from fixed seeds, timestamps are fixed. Re-running must be a byte no-op
(CI drift gate).

The vectors pin verifier behavior in TS, Python, and C#: Ed25519 signature over the exact
UTF-8 bytes of `payload`, then parse, then body schema/shape, then TTL (against the case's
fixed verify_at, boundary-inclusive), then seq monotonicity (against last_committed_seq),
then op allowlist + args validation.

The payload is built with sorted keys / compact separators over integer-and-string content,
which coincides with RFC 8785 for this value class; the gateway uses a real JCS library.
Verifiers never canonicalize — they verify received bytes — so these vectors are
canonicalization-agnostic by design.
"""

import hashlib
import json
import pathlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

OUT = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "conformance"
OUT.mkdir(parents=True, exist_ok=True)
IDMAP_OUT = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "idmap"
IDMAP_OUT.mkdir(parents=True, exist_ok=True)

SEED = bytes.fromhex("f00dfeed" * 8)          # 32-byte test-only seed (not a secret)
WRONG_SEED = bytes.fromhex("deadbeef" * 8)

KEY = Ed25519PrivateKey.from_private_bytes(SEED)
WRONG_KEY = Ed25519PrivateKey.from_private_bytes(WRONG_SEED)
PUBLIC_HEX = KEY.public_key().public_bytes_raw().hex()

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


def sign(payload: str, key: Ed25519PrivateKey = KEY) -> str:
    return key.sign(payload.encode("utf-8")).hex()


def envelope(body, key: Ed25519PrivateKey = KEY):
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
malformed = {"payload": not_json_payload, "sig": sign(not_json_payload)}
no_workstation = envelope({k: v for k, v in BODY.items() if k != "workstation_id"})
null_ops = envelope({**BODY, "ops": None})
empty_ops = envelope({**BODY, "ops": []})
args_not_object = envelope({**BODY, "ops": [{"op": "create_level", "args": 42}]})
bad_issued_at = envelope({**BODY, "issued_at": "2026-01-01"})
uppercase_sig = {"payload": valid["payload"], "sig": valid["sig"].upper()}
non_hex_sig = {"payload": valid["payload"], "sig": "zz" * 64}
non_ascii_sig = {"payload": valid["payload"], "sig": "café" + valid["sig"][4:]}
# Pins the HMAC->Ed25519 format change: an old-style 64-hex value must fail the sig-format
# guard in all three implementations, never reach the signature check.
wrong_length_sig = {"payload": valid["payload"], "sig": valid["sig"][:64]}


def case(name, env, expect, reason=None, verify_at="2026-01-01T00:05:00Z", last_seq=1):
    c = {
        "name": name,
        "envelope": env,
        "verify_at": verify_at,
        "last_committed_seq": last_seq,
        "expect": expect,
    }
    if reason:
        c["reason"] = reason
    return c


manifest = {
    "description": "Signing/verification conformance vectors. Every implementation (TS, Python, C# Core) must produce these exact outcomes. sig = hex Ed25519 signature (RFC 8032) over the UTF-8 bytes of payload; public_key_hex is the verifier input. private_seed_hex is TEST-ONLY (gateway signer tests + sim/plugin test signing) — production private keys never leave the gateway. verify_at is the injected 'now'; last_committed_seq is the persisted state the seq check runs against.",
    "public_key_hex": PUBLIC_HEX,
    "private_seed_hex": SEED.hex(),
    "cases": [
        case("valid", valid, "accepted"),
        case("expired_ttl", valid, "rejected", "expired_ttl", verify_at="2026-01-01T00:20:00Z"),
        case("tampered_payload", tampered, "rejected", "bad_signature"),
        case("wrong_key", wrong_key, "rejected", "bad_signature"),
        case("replayed_seq", valid, "rejected", "bad_seq", last_seq=2),
        case("unknown_op", envelope(unknown_op_body), "rejected", "unknown_op"),
        case("invalid_args", envelope(invalid_args_body), "rejected", "invalid_args"),
        case("ttl_boundary_accept", valid, "accepted", verify_at="2026-01-01T00:10:00Z"),
        case(
            "ttl_boundary_plus_one_second", valid, "rejected", "expired_ttl",
            verify_at="2026-01-01T00:10:01Z",
        ),
        case("malformed_payload_valid_sig", malformed, "rejected", "schema_invalid"),
        case("missing_workstation_id", no_workstation, "rejected", "schema_invalid"),
        case("null_ops", null_ops, "rejected", "schema_invalid"),
        case("empty_ops", empty_ops, "rejected", "schema_invalid"),
        case("args_not_an_object", args_not_object, "rejected", "schema_invalid"),
        case("bad_issued_at_date_only", bad_issued_at, "rejected", "schema_invalid"),
        case("uppercase_hex_sig", uppercase_sig, "rejected", "bad_signature"),
        case("non_hex_sig", non_hex_sig, "rejected", "bad_signature"),
        case("non_ascii_sig", non_ascii_sig, "rejected", "bad_signature"),
        case("sig_wrong_length_64", wrong_length_sig, "rejected", "bad_signature"),
    ],
}

path = OUT / "manifest.json"
path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {path} ({len(manifest['cases'])} cases)")


# ---------------------------------------------------------------------------
# id-map hash cases: hello.id_map_hash and the drift gate require gateway (TS),
# sim (Python), and plugin (C#) to compute the identical hash. Definition:
#   sha256( UTF-8( JCS( [[logical_id, element_id], ...] sorted by logical_id ) ) )
# For this value class (ASCII ids per the contract patterns, integer element ids),
# compact sorted json.dumps coincides with RFC 8785.
# ---------------------------------------------------------------------------

def id_map_hash(entries: dict[str, int]) -> str:
    pairs = [[k, entries[k]] for k in sorted(entries)]
    doc = json.dumps(pairs, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(doc.encode("utf-8")).hexdigest()


IDMAP_CASES = [
    {"name": "empty", "entries": {}},
    {"name": "single", "entries": {"W-001": 316222}},
    {
        "name": "multi_unsorted_input",
        "entries": {"W-002": 316223, "D-001": 316501, "W-001": 316222, "N-001": 316777},
    },
    {
        "name": "full_commit0",
        "entries": {
            "W-001": 1000001, "W-002": 1000002, "W-003": 1000003, "W-004": 1000004,
            "D-001": 1000101, "N-001": 1000201, "R-001": 1000301, "F-001": 1000401,
        },
    },
]

idmap_doc = {
    "description": "Cross-language id-map hash cases: sha256 over the UTF-8 bytes of the JCS serialization of [[logical_id, element_id], ...] sorted by logical_id (codepoint order). Implemented by idMapHash (TS), chapter_contracts.id_map_hash (Python), and ChapterHub.Core IdMapHash (C#).",
    "cases": [
        {**c, "expected_hash": id_map_hash(c["entries"])} for c in IDMAP_CASES
    ],
}

idmap_path = IDMAP_OUT / "hash_cases.json"
idmap_path.write_text(json.dumps(idmap_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {idmap_path} ({len(IDMAP_CASES)} cases)")
