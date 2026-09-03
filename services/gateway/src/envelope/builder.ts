// Envelope construction: validate ops against the registry BEFORE signing (SI-2's
// upstream half), then the set_parameter allowlist (SI-4), canonicalize the body ONCE
// (RFC 8785), sign with the per-project Ed25519 key. Verifiers hash/verify received
// bytes; they never re-canonicalize.
import { randomUUID } from "node:crypto";
import canonicalize from "canonicalize";
import { validateOps } from "@chapter/contracts";
import { signPayload } from "../crypto/keystore.js";
import { checkParamAllowlist } from "./param-allowlist.js";

export interface OpInput {
  op: string;
  args: Record<string, unknown>;
}

export interface BuildRequest {
  projectId: string;
  workstationId: string;
  seq: number;
  ops: OpInput[];
  ttlS: number;
  commitLabel?: string;
  approvalRef?: { review_id: string; content_hash: string };
  issuedAt: Date;
}

export type BuildResult =
  | { ok: true; envelopeId: string; payload: string; sig: string; issuedAt: string }
  | { ok: false; error: { index: number; op: string; reason: string; detail?: string } };

export function buildEnvelope(req: BuildRequest, seedEnc: Buffer, masterKey: Buffer): BuildResult {
  const problem = validateOps(req.ops);
  if (problem) return { ok: false, error: problem };
  // SI-4 at the signer (Phase 7): set_parameter only on allowlisted params for the
  // target's category — kept OUT of @chapter/contracts validateOps, which is the TS half
  // of the conformance-pinned three-language envelope verifier
  const allowlist = checkParamAllowlist(req.ops);
  if (allowlist) return { ok: false, error: allowlist };

  const envelopeId = randomUUID();
  const issuedAt = req.issuedAt.toISOString();
  const body: Record<string, unknown> = {
    envelope_id: envelopeId,
    project_id: req.projectId,
    workstation_id: req.workstationId,
    seq: req.seq,
    issued_at: issuedAt,
    ttl_s: req.ttlS,
    ops: req.ops,
  };
  if (req.commitLabel !== undefined) body.commit_label = req.commitLabel;
  if (req.approvalRef !== undefined) body.approval_ref = req.approvalRef;

  const payload = canonicalize(body);
  if (payload === undefined) throw new Error("uncanonicalizable envelope body");
  return { ok: true, envelopeId, payload, sig: signPayload(payload, seedEnc, masterKey), issuedAt };
}
