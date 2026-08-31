// Envelope construction: validate ops against the registry BEFORE signing (SI-2's
// upstream half), canonicalize the body ONCE (RFC 8785), sign with the per-project
// Ed25519 key. Verifiers hash/verify received bytes; they never re-canonicalize.
import { randomUUID } from "node:crypto";
import canonicalize from "canonicalize";
import { validateOps } from "@chapter/contracts";
import { signPayload } from "../crypto/keystore.js";

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
