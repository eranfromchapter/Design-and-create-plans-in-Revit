// Envelope verification — the TS reference implementation of the D3 contract.
// Order: sig (Ed25519 over received payload bytes) → parse → body schema → TTL → seq →
// op allowlist → per-op args_schema. Mirrored by revit-sim (Python) and
// ChapterHub.Core (C#); the shared conformance vectors pin all three.
import { Ajv2020, type ValidateFunction } from "ajv/dist/2020.js";
import { fullFormats } from "ajv-formats/dist/formats.js";
import { ed25519VerifyHex } from "./ed25519.js";
import envelopeSchema from "../../schemas/command-envelope.v1.json" with { type: "json" };
import registry from "../../ops/registry.json" with { type: "json" };

export type RejectReason =
  | "bad_signature"
  | "expired_ttl"
  | "bad_seq"
  | "unknown_op"
  | "invalid_args"
  | "schema_invalid";

export type VerifyResult =
  | { status: "accepted"; body: EnvelopeBody }
  | { status: "rejected"; reason: RejectReason };

export interface EnvelopeBody {
  envelope_id: string;
  project_id: string;
  workstation_id: string;
  seq: number;
  issued_at: string;
  ttl_s: number;
  commit_label?: string;
  approval_ref?: { review_id: string; content_hash: string };
  ops: { op: string; args: Record<string, unknown> }[];
}

const ajv = new Ajv2020({ allErrors: false, strict: false, formats: fullFormats });

const bodySchema = {
  ...(envelopeSchema.$defs.EnvelopeBody as Record<string, unknown>),
  $defs: envelopeSchema.$defs as Record<string, unknown>,
};
const validateBody = ajv.compile(bodySchema);

const argsValidators = new Map<string, ValidateFunction>(
  Object.entries(registry.ops).map(([op, entry]) => [
    op,
    ajv.compile((entry as { args_schema: Record<string, unknown> }).args_schema),
  ]),
);

/**
 * Verify a wire envelope {payload, sig}.
 *
 * @param publicKeyHex  raw 64-hex per-project Ed25519 public key (delivered at enrollment)
 * @param verifyAt   injected "now" (tests use the manifest's fixed instants)
 * @param lastCommittedSeq  persisted seq state the monotonicity check runs against
 */
export function verifyEnvelope(
  envelope: { payload: string; sig: string },
  publicKeyHex: string,
  verifyAt: Date,
  lastCommittedSeq: number,
): VerifyResult {
  // The sig contract is 128 lowercase hex chars (D3); other spellings never reach the
  // signature check, keeping all three implementations agreed on what verifies.
  if (!/^[0-9a-f]{128}$/.test(envelope.sig)) {
    return { status: "rejected", reason: "bad_signature" };
  }
  if (!ed25519VerifyHex(envelope.payload, envelope.sig, publicKeyHex)) {
    return { status: "rejected", reason: "bad_signature" };
  }

  let body: unknown;
  try {
    body = JSON.parse(envelope.payload);
  } catch {
    return { status: "rejected", reason: "schema_invalid" };
  }
  if (!validateBody(body)) return { status: "rejected", reason: "schema_invalid" };
  const b = body as EnvelopeBody;

  const expiresMs = Date.parse(b.issued_at) + b.ttl_s * 1000;
  if (!(verifyAt.getTime() <= expiresMs)) return { status: "rejected", reason: "expired_ttl" };

  if (!(b.seq > lastCommittedSeq)) return { status: "rejected", reason: "bad_seq" };

  for (const { op, args } of b.ops) {
    const validateArgs = argsValidators.get(op);
    if (!validateArgs) return { status: "rejected", reason: "unknown_op" };
    if (!validateArgs(args)) return { status: "rejected", reason: "invalid_args" };
  }

  return { status: "accepted", body: b };
}

/**
 * Builder-side op validation (gateway, BEFORE signing — SI-2 upstream half): returns the
 * first problem or null when every op is allowlisted with schema-valid args.
 */
export function validateOps(
  ops: { op: string; args: unknown }[],
): { index: number; op: string; reason: "unknown_op" | "invalid_args"; detail?: string } | null {
  for (const [index, { op, args }] of ops.entries()) {
    const validateArgs = argsValidators.get(op);
    if (!validateArgs) return { index, op, reason: "unknown_op" };
    if (!validateArgs(args)) {
      return { index, op, reason: "invalid_args", detail: ajv.errorsText(validateArgs.errors) };
    }
  }
  return null;
}
