// Provenance verification of a MergeResult BEFORE it becomes a commit2_merge review
// (docs/PHASE6_DESIGN.md §5.2). The merge gate is a trusted service, but the merged
// ops are what the human approves and the executor runs, so the gateway proves them
// against the two APPROVED branch reviews it holds:
//   - every op is one of the five merge ops; exactly one trailing run_interference_check;
//   - every furniture/device/pipe/conduit id comes from a branch (or is a re-derived
//     conduit id, see below); dropped ids are branch ids;
//   - an op the merge did NOT act on deep-equals (JCS) the approved branch op. Derived
//     state is exempt: conduits are re-derived from the raceway tree after ANY re-plan
//     (PIN-27), pipes after a relocate_stack; a device/furniture op may differ only when
//     an action names it (lower) — or a relegalize/shift replayed from prior actions;
//   - the embedded branch hashes equal the live review rows.
// Any violation → commit2_failure {code: merge_ops_unverified} + 422, never a card.
import canonicalize from "canonicalize";
import type { MergeResult } from "./merge-client.js";

export interface BranchOps {
  interior: { review_id?: string; content_hash: string; ops: { op: string; args: Record<string, unknown> }[] };
  mep: { review_id?: string; content_hash: string; ops: { op: string; args: Record<string, unknown> }[] };
}

/** Actions after which P-1..P-4 re-ran: every pipe op is derived state (ids renumber). */
const PIPE_REPLANS = new Set(["relocate_stack", "replan_plumbing"]);
export const CLASH_ID = /^([A-Z]{1,2}-[0-9]{2,4}|revit:[0-9]+)$/;

export type VerifyOutcome = { ok: true } | { ok: false; code: "merge_ops_unverified"; detail: string };

const CONDUIT_ID = /^Q-\d{3,4}$/;
const PIPE_ID = /^P-\d{3,4}$/;

export function verifyMergeResult(
  result: MergeResult,
  branches: BranchOps,
  priorActions: { lower?: string; action?: string }[] = [],
): VerifyOutcome {
  const fail = (detail: string): VerifyOutcome => ({ ok: false, code: "merge_ops_unverified", detail });
  if (result.interior.content_hash !== branches.interior.content_hash) return fail("interior content_hash mismatch");
  if (result.mep.content_hash !== branches.mep.content_hash) return fail("mep content_hash mismatch");
  if (branches.interior.review_id !== undefined && result.interior.review_id !== branches.interior.review_id) {
    return fail("interior review_id mismatch");
  }
  if (branches.mep.review_id !== undefined && result.mep.review_id !== branches.mep.review_id) {
    return fail("mep review_id mismatch");
  }
  if (result.status !== "clean") return { ok: true }; // no ops to verify; the caller files a failure review

  const ops = result.ops;
  if (ops.length === 0) return fail("empty merged ops");
  const checks = ops.filter((o) => o.op === "run_interference_check");
  if (checks.length !== 1 || ops[ops.length - 1]!.op !== "run_interference_check") {
    return fail("exactly one trailing run_interference_check required");
  }
  const branchOps = new Map<string, { op: string; args: Record<string, unknown> }>();
  for (const op of [...branches.interior.ops, ...branches.mep.ops]) {
    const id = op.args["id"];
    if (typeof id === "string") branchOps.set(id, op);
  }
  const acted = new Set<string>();
  for (const a of [...priorActions, ...result.actions]) if (a.lower) acted.add(a.lower);
  for (const id of result.dropped) {
    if (!branchOps.has(id) && !CONDUIT_ID.test(id)) return fail(`dropped id ${id} is not a branch id`);
  }
  const relocated = [...priorActions, ...result.actions].some((a) => PIPE_REPLANS.has(a.action ?? ""));
  const seen = new Set<string>();
  for (const op of ops.slice(0, -1)) {
    const id = op.args["id"];
    if (typeof id !== "string") return fail(`${op.op} without id`);
    if (seen.has(id)) return fail(`duplicate id ${id}`);
    seen.add(id);
    if (result.dropped.includes(id)) return fail(`dropped id ${id} still present`);
    const approved = branchOps.get(id);
    if (op.op === "create_conduit") {
      if (!CONDUIT_ID.test(id)) return fail(`conduit id ${id} malformed`);
      continue; // derived state (PIN-27)
    }
    if (op.op === "create_pipe") {
      if (!PIPE_ID.test(id)) return fail(`pipe id ${id} malformed`);
      if (relocated) continue; // P-1..P-4 re-ran: ids and geometry legitimately differ
    }
    if (!approved) return fail(`id ${id} is not in either approved branch`);
    if (approved.op !== op.op) return fail(`op kind changed for ${id}`);
    if (acted.has(id)) continue;
    if (canonicalize(op.args) !== canonicalize(approved.args)) {
      return fail(`un-actioned op ${id} differs from the approved branch`);
    }
  }
  // completeness: every approved op survives, is dropped, or is derived state
  for (const [id, approved] of branchOps) {
    if (approved.op === "create_conduit") continue;
    if (approved.op === "create_pipe" && relocated) continue;
    if (!seen.has(id) && !result.dropped.includes(id)) {
      return fail(`approved op ${id} vanished without a drop`);
    }
  }
  const interiorIds = branches.interior.ops.map((o) => o.args["id"] as string);
  const interiorVerbatim = interiorIds.every((id) => {
    const merged = ops.find((o) => o.args["id"] === id);
    return merged !== undefined && canonicalize(merged.args) === canonicalize(branchOps.get(id)!.args);
  });
  if (result.interior.ops_verbatim !== interiorVerbatim) {
    return fail(`interior.ops_verbatim=${result.interior.ops_verbatim} contradicts the ops`);
  }
  return { ok: true };
}

/** Pairs from a rolled-back commit_result: every `interference` error carries "A~B". */
export function clashPairsFromErrors(errors: unknown[]): { a_id: string; b_id: string; kind: string }[] {
  const pairs: { a_id: string; b_id: string; kind: string }[] = [];
  for (const e of errors) {
    const err = e as { code?: unknown; message?: unknown };
    if (err.code !== "interference" || typeof err.message !== "string") continue;
    const parts = err.message.trim().split("~");
    if (parts.length !== 2 || !CLASH_ID.test(parts[0]!) || !CLASH_ID.test(parts[1]!)) continue;
    pairs.push({ a_id: parts[0]!, b_id: parts[1]!, kind: "hard_interference" });
  }
  return pairs;
}

/** Codes the executor may return that are NOT a clash and NOT transient: the merged
 *  plan itself is wrong for this model → commit2_failure, never a re-issue. */
export function isHardRollback(errors: unknown[]): boolean {
  return errors.some((e) => {
    const code = (e as { code?: unknown }).code;
    return typeof code === "string" && code !== "interference" && code !== "expired_ttl";
  });
}
