// Phase 6 gateway flow (docs/PHASE6_DESIGN.md §5): plan-mep -> mep_plan review (the MEP
// branch delta), merge-commit2 -> commit2_merge review (the merged Commit #2 under the
// shared ≤3-round clash budget, derived from the merge chain), issue-commit2 -> the
// "Commit #2" envelope under a fresh seq. Every rebuilt merged plan is a NEW review a
// human approves (AUTO_APPROVE covers CI only); failures are never auto-approved.
import type { FastifyInstance, FastifyReply } from "fastify";
import { z } from "zod";
import type { Config } from "../config.js";
import {
  MERGE_BUDGET,
  envelopeClashPairs,
  envelopeHasInterference,
  type EnvelopeRow,
  type Repos,
  type ReviewRow,
} from "../db/repos.js";
import type { OpInput } from "../envelope/builder.js";
import { requireActor, requireService, resolveActor } from "./auth.js";
import { planMep, type MepConfirmations } from "../layout/mep-client.js";
import { mergeCommit2, type MergeAction } from "../layout/merge-client.js";
import { verifyMergeResult } from "../layout/merge-verify.js";

export const mepConfirmationsSchema = z
  .object({
    panel: z.tuple([z.number().finite(), z.number().finite()]).optional(),
    slab_to_slab_mm: z.number().min(2100).max(6000).optional(),
  })
  .strict();
const planMepBody = z.object({ confirmations: mepConfirmationsSchema.optional() }).default({});

export const PANEL_WALL_TOLERANCE_MM = 600;
export const COMMIT2_REISSUE_CAP = 3;
const TRANSIENT_MERGE_ERRORS = new Set(["merge_timeout", "merge_error", "layout_compiler_unreachable"]);

export interface IssueSpec {
  ops: OpInput[];
  ttlS?: number;
  commitLabel?: string;
  approvalRef?: { review_id: string; content_hash: string };
  seqPolicy?: "next_committed" | "next_issued";
  reissueOf?: string;
  /** Phase 7: runs after the envelope row is inserted and BEFORE the frame is sent (the
   *  render job must exist before any export_ready can arrive). */
  beforeDispatch?: (envelopeId: string, seq: number) => Promise<void>;
}

type IssueFn = (reply: FastifyReply, projectId: string, spec: IssueSpec) => Promise<FastifyReply>;

export interface Outcome {
  code: number;
  body: unknown;
}

interface Wall {
  start: [number, number];
  end: [number, number];
}

function pointToSegmentMm(p: [number, number], w: Wall): number {
  const [x, y] = p;
  const [x1, y1] = w.start;
  const [x2, y2] = w.end;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / len2));
  return Math.hypot(x - (x1 + t * dx), y - (y1 + t * dy));
}

export function panelOnWall(panel: [number, number], walls: Wall[]): boolean {
  return walls.some((w) => pointToSegmentMm(panel, w) <= PANEL_WALL_TOLERANCE_MM);
}

export type InteriorReadiness =
  | { ready: true; plan: ReviewRow }
  | { ready: false; reason: "none" | "pending" | "rejected" | "stale_brief"; plan: ReviewRow | null };

export function registerCommit2Routes(
  app: FastifyInstance,
  deps: { config: Config; repos: Repos },
  issueEnvelope: IssueFn,
): void {
  const { config, repos } = deps;
  const serviceAuth = requireService(config);
  const actorAuth = requireActor(config);

  async function interiorReadiness(projectId: string): Promise<InteriorReadiness> {
    const plan = await repos.latestReviewOfKind(projectId, "interior_plan");
    if (!plan) return { ready: false, reason: "none", plan: null };
    if (plan.status === "pending") return { ready: false, reason: "pending", plan };
    if (plan.status === "rejected") return { ready: false, reason: "rejected", plan };
    const confirmed = await repos.latestConfirmedBrief(projectId);
    const version = (plan.content as { brief_version?: number }).brief_version;
    if (!confirmed || version !== confirmed.brief_version) {
      return { ready: false, reason: "stale_brief", plan };
    }
    return { ready: true, plan };
  }

  /** Shared Commit #2 preconditions: 404 -> commit0 -> commit1 -> commit2_already_done ->
   *  a Commit #2 envelope in flight. Returns the reply when the ladder fails. */
  async function commit2Guards(
    projectId: string,
    opts: { requireCompiler: boolean },
  ): Promise<Outcome | null> {
    if (!(await repos.getProject(projectId))) return { code: 404, body: { error: "unknown_project" } };
    if (opts.requireCompiler && !config.layoutCompilerUrl) {
      return { code: 503, body: { error: "layout_compiler_unavailable" } };
    }
    if (!(await repos.hasSnapshot(projectId, "commit0"))) {
      return { code: 409, body: { error: "commit0_not_done" } };
    }
    if (!(await repos.hasSnapshot(projectId, "commit1"))) {
      return { code: 409, body: { error: "commit1_not_done" } };
    }
    if (await repos.hasSnapshot(projectId, "commit2")) {
      return { code: 409, body: { error: "commit2_already_done" } };
    }
    const inflight = await repos.inflightEnvelope(projectId);
    if (inflight && inflight.commit_label === "Commit #2") {
      return { code: 409, body: { error: "commit2_envelope_in_flight", envelope_id: inflight.envelope_id } };
    }
    return null;
  }

  const send = (reply: FastifyReply, out: Outcome): FastifyReply => reply.code(out.code).send(out.body);

  // ---- plan-mep -------------------------------------------------------------------

  async function runPlanMep(
    projectId: string,
    confirmations: MepConfirmations | undefined,
  ): Promise<Outcome> {
    const guarded = await commit2Guards(projectId, { requireCompiler: true });
    if (guarded) return guarded;
    const readiness = await interiorReadiness(projectId);
    if (!readiness.ready) {
      return { code: 409, body: { error: "interior_plan_not_ready", reason: readiness.reason } };
    }
    const interior = readiness.plan;
    const commit0 = (await repos.getSnapshot(projectId, "commit0"))!;
    const commit1 = (await repos.getSnapshot(projectId, "commit1"))!;
    const commit1Review = await repos.getReview(commit1.review_id);
    if (!commit1Review) return { code: 409, body: { error: "no_commit1_review" } };

    // confirmations carry forward from the latest mep_plan when the caller omits them
    // (the card's human-suppliable field: panel + slab-to-slab)
    const previous = confirmations === undefined
      ? await repos.latestReviewOfKind(projectId, "mep_plan")
      : null;
    const effective: MepConfirmations =
      confirmations ??
      ((previous?.content as { confirmations?: MepConfirmations } | undefined)?.confirmations ?? {});
    const content = interior.content as {
      layout: { walls: Wall[] };
      ops: unknown[];
      brief_version: number;
      diagnostics?: { items?: { item_id?: string; wall_id?: string }[] };
    };
    if (effective.panel && !panelOnWall(effective.panel, content.layout.walls)) {
      return {
        code: 422,
        body: {
          error: "panel_not_on_wall",
          message: `panel must lie within ${PANEL_WALL_TOLERANCE_MM} mm of a wall centerline`,
        },
      };
    }
    const placerWallIds: Record<string, string> = {};
    for (const d of content.diagnostics?.items ?? []) {
      if (d.item_id && d.wall_id) placerWallIds[d.item_id] = d.wall_id;
    }

    const outcome = await planMep(config.layoutCompilerUrl!, {
      project_id: projectId,
      commit0_layout: commit0.layout,
      commit1_layout: commit1.layout,
      commit1_ops: (commit1Review.content as { ops: unknown[] }).ops,
      interior_ops: content.ops,
      furnished_layout: content.layout,
      placer_wall_ids: placerWallIds,
      confirmations: effective,
    });
    if (!outcome.ok) {
      await repos.createReview(
        projectId,
        "mep_failure",
        {
          error: outcome.error,
          message: outcome.message,
          brief_version: content.brief_version,
          interior_review_id: interior.id,
          confirmations: effective,
        },
        false,
      );
      await repos.logEventDirect(projectId, "gateway", "plan_mep_failed", {
        error: outcome.error,
        message: outcome.message,
        raw_outputs: outcome.rawOutputs,
      });
      return { code: 422, body: { error: outcome.error, message: outcome.message } };
    }
    const { plan } = outcome;
    // re-runs allowed: the latest mep_plan wins (a newer plan starts a fresh chain)
    const review = await repos.createReview(
      projectId,
      "mep_plan",
      {
        ...plan,
        brief_version: content.brief_version,
        interior_review_id: interior.id,
        interior_content_hash: interior.content_hash,
        confirmations: effective,
      },
      config.autoApprove,
    );
    return {
      code: 201,
      body: {
        review_id: review.id,
        content_hash: review.content_hash,
        status: review.status,
        counts: plan.counts,
        blocking: plan.blocking,
      },
    };
  }

  app.post("/projects/:id/plan-mep", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const body = planMepBody.parse(req.body ?? {});
    return send(reply, await runPlanMep(projectId, body.confirmations));
  });

  // the card's form: panel x/y + slab-to-slab, then back to the reviews page
  app.post("/ui/projects/:id/plan-mep", { preHandler: actorAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const form = (req.body ?? {}) as Record<string, string>;
    const num = (key: string): number | undefined => {
      const raw = form[key];
      if (raw === undefined || raw === "") return undefined;
      const n = Number(raw);
      return Number.isFinite(n) ? n : Number.NaN;
    };
    const px = num("panel_x");
    const py = num("panel_y");
    const slab = num("slab_to_slab_mm");
    const candidate: Record<string, unknown> = {};
    if (px !== undefined || py !== undefined) candidate["panel"] = [px, py];
    if (slab !== undefined) candidate["slab_to_slab_mm"] = slab;
    const parsed = mepConfirmationsSchema.safeParse(candidate);
    if (!parsed.success) return reply.code(422).send({ error: "bad_confirmations" });
    const actorToken = resolveActor(config, req) ? ((req.query as { actor_token?: string }).actor_token ?? "") : "";
    const out = await runPlanMep(projectId, parsed.data);
    if (out.code === 201) {
      return reply.code(302).redirect(`/ui/projects/${projectId}/reviews?actor_token=${encodeURIComponent(actorToken)}`);
    }
    return send(reply, out);
  });

  // ---- merge-commit2 --------------------------------------------------------------

  app.post("/projects/:id/merge-commit2", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const guarded = await commit2Guards(projectId, { requireCompiler: true });
    if (guarded) return send(reply, guarded);
    const readiness = await interiorReadiness(projectId);
    if (!readiness.ready) {
      return reply.code(409).send({ error: "interior_plan_not_ready", reason: readiness.reason });
    }
    const interior = readiness.plan;
    const mep = await repos.latestReviewOfKind(projectId, "mep_plan");
    if (!mep) return reply.code(409).send({ error: "no_mep_plan" });
    if (mep.status !== "approved") {
      return reply.code(409).send({ error: "mep_plan_not_approved", status: mep.status });
    }
    const mepContent = mep.content as {
      interior_review_id?: string;
      counts: { blocking: number };
      blocking: string[];
      ops: OpInput[];
      brief_version: number;
    };
    if (mepContent.interior_review_id !== interior.id) {
      return reply.code(409).send({ error: "mep_plan_stale" });
    }
    if (mepContent.counts.blocking > 0) {
      return reply.code(409).send({ error: "mep_review_items_open", codes: mepContent.blocking });
    }
    const pending = await repos.pendingReviewOfKind(projectId, "commit2_merge");
    if (pending) return reply.code(409).send({ error: "merge_review_pending", review_id: pending.id });
    const chain = await repos.mergeChain(projectId);
    if (chain.failed) return reply.code(409).send({ error: "merge_chain_failed" });

    let iterationsUsed = 0;
    let iteration = 1;
    let priorActions: MergeAction[] = [];
    let clashPairs = [] as ReturnType<typeof envelopeClashPairs>;
    const latest = chain.latest;
    if (latest && latest.status === "approved") {
      const env: EnvelopeRow | null = chain.envelope;
      const latestContent = latest.content as {
        iterations_used: number;
        iteration: number;
        actions: MergeAction[];
        prior_actions?: MergeAction[];
      };
      if (!env || env.status === "issued" || env.status === "ack_accepted") {
        return reply.code(409).send({ error: "merge_review_awaiting_issue", review_id: latest.id });
      }
      if (env.status === "committed") {
        return reply.code(409).send({ error: "commit2_already_done" });
      }
      if (!envelopeHasInterference(env)) {
        // ack_rejected | expired | rolled_back for a transient code: same plan again
        return reply.code(409).send({ error: "merge_review_reissuable", review_id: latest.id, envelope_status: env.status });
      }
      iterationsUsed = latestContent.iterations_used;
      if (iterationsUsed >= MERGE_BUDGET) {
        // one REVIEW card per exhausted plan — a polling client never piles up duplicates
        const existing = await repos.pendingReviewOfKind(projectId, "commit2_failure");
        const dup = existing && (existing.content as { merge_review_id?: string; reason?: string });
        if (!(dup && dup.merge_review_id === latest.id && dup.reason === "merge_budget_exhausted")) {
          await repos.createReview(
            projectId,
            "commit2_failure",
            {
              reason: "merge_budget_exhausted",
              hard: false,
              merge_review_id: latest.id,
              envelope_id: env.envelope_id,
              iterations_used: iterationsUsed,
              clash_pairs: envelopeClashPairs(env),
              chain: { interior_review_id: interior.id, mep_review_id: mep.id },
            },
            false,
          );
        }
        return reply.code(409).send({ error: "merge_budget_exhausted", iterations_used: iterationsUsed });
      }
      iteration = latestContent.iteration + 1;
      priorActions = [...(latestContent.prior_actions ?? []), ...latestContent.actions];
      clashPairs = envelopeClashPairs(env);
    }

    const commit0 = (await repos.getSnapshot(projectId, "commit0"))!;
    const commit1 = (await repos.getSnapshot(projectId, "commit1"))!;
    const commit1Review = await repos.getReview(commit1.review_id);
    if (!commit1Review) return reply.code(409).send({ error: "no_commit1_review" });
    const interiorContent = interior.content as { ops: OpInput[]; layout: unknown };
    // the MepPlan verbatim = the mep_plan content minus the gateway-stamped keys
    const STAMPED = new Set(["brief_version", "interior_review_id", "interior_content_hash", "confirmations"]);
    const plan = Object.fromEntries(
      Object.entries(mep.content as Record<string, unknown>).filter(([k]) => !STAMPED.has(k)),
    );

    const outcome = await mergeCommit2(config.layoutCompilerUrl!, {
      project_id: projectId,
      commit0_layout: commit0.layout,
      commit1_ops: (commit1Review.content as { ops: unknown[] }).ops,
      interior: {
        review_id: interior.id,
        content_hash: interior.content_hash,
        ops: interiorContent.ops,
        layout: interiorContent.layout,
      },
      mep: { review_id: mep.id, content_hash: mep.content_hash, plan },
      iterations_used: iterationsUsed,
      iteration,
      prior_actions: priorActions,
      clash_pairs: clashPairs,
    });
    const failure = async (content: Record<string, unknown>, hard: boolean) =>
      repos.createReview(
        projectId,
        "commit2_failure",
        {
          ...content,
          hard,
          iteration,
          iterations_used: iterationsUsed,
          chain: { interior_review_id: interior.id, mep_review_id: mep.id },
        },
        false,
      );
    if (!outcome.ok) {
      // a timeout / unreachable compiler says nothing about the plan: retryable (hard=false);
      // a contract refusal (clash_pair_unknown, merge_internal, ...) is the plan's fault
      const transient = TRANSIENT_MERGE_ERRORS.has(outcome.error);
      await failure({ reason: "merge_error", error: outcome.error, message: outcome.message }, !transient);
      await repos.logEventDirect(projectId, "gateway", "merge_failed", {
        error: outcome.error,
        message: outcome.message,
        raw_outputs: outcome.rawOutputs,
      });
      return reply.code(422).send({ error: outcome.error, message: outcome.message });
    }
    const { result } = outcome;
    const verified = verifyMergeResult(
      result,
      {
        interior: { review_id: interior.id, content_hash: interior.content_hash, ops: interiorContent.ops },
        mep: { review_id: mep.id, content_hash: mep.content_hash, ops: mepContent.ops },
      },
      priorActions,
    );
    if (!verified.ok) {
      await failure({ reason: verified.code, detail: verified.detail }, true);
      return reply.code(422).send({ error: verified.code, detail: verified.detail });
    }
    if (result.status !== "clean") {
      // REVIEW: the merge gate could not resolve within the budget (or hit a
      // same-priority pair) — a human decides; nothing is issued
      await failure(
        {
          reason: result.status,
          blocked_reason: result.blocked_reason,
          clash_report: result.clash_report,
          actions: result.actions,
          dropped: result.dropped,
        },
        false,
      );
      return reply.code(409).send({ error: "merge_review_required", status: result.status });
    }
    const review = await repos.createReview(
      projectId,
      "commit2_merge",
      {
        ...result,
        prior_actions: priorActions,
        brief_version: mepContent.brief_version,
      },
      config.autoApprove,
    );
    return reply.code(201).send({
      review_id: review.id,
      content_hash: review.content_hash,
      status: review.status,
      iteration: result.iteration,
      iterations_used: result.iterations_used,
      counts: result.counts,
      clash_summary: {
        budget: result.clash_report.budget,
        actions: result.actions.length,
        dropped: result.dropped.length,
        replan_deltas: result.replan_deltas.length,
        interior_verbatim: result.interior.ops_verbatim,
      },
    });
  });

  // ---- issue-commit2 --------------------------------------------------------------

  app.post("/projects/:id/issue-commit2", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const guarded = await commit2Guards(projectId, { requireCompiler: false });
    if (guarded) return send(reply, guarded);
    const chain = await repos.mergeChain(projectId);
    const review = chain.latest;
    if (!review) {
      // a merged plan may exist for an older chain — that one is stale
      const any = await repos.latestReviewOfKind(projectId, "commit2_merge");
      return reply.code(409).send({ error: any ? "merge_review_stale" : "no_merge_review" });
    }
    if (review.status !== "approved") {
      return reply.code(409).send({ error: "merge_review_not_approved", status: review.status });
    }
    const env = chain.envelope;
    if (env && (env.status === "issued" || env.status === "ack_accepted")) {
      return reply.code(409).send({ error: "envelope_in_flight", envelope_id: env.envelope_id });
    }
    if (envelopeHasInterference(env)) {
      return reply.code(409).send({ error: "merge_review_consumed", review_id: review.id });
    }
    const reissues = await repos.envelopeCountForReview(review.id);
    if (reissues >= COMMIT2_REISSUE_CAP) {
      // three transient failures of the same plan: the chain is done (hard) — a new
      // mep_plan restarts it; the card is filed once
      const existing = await repos.pendingReviewOfKind(projectId, "commit2_failure");
      const dup = existing && (existing.content as { merge_review_id?: string; reason?: string });
      if (!(dup && dup.merge_review_id === review.id && dup.reason === "merge_review_reissue_exhausted")) {
        await repos.createReview(
          projectId,
          "commit2_failure",
          {
            reason: "merge_review_reissue_exhausted",
            hard: true,
            merge_review_id: review.id,
            reissues,
            chain: { interior_review_id: chain.interior!.id, mep_review_id: chain.mep!.id },
          },
          false,
        );
      }
      return reply.code(409).send({ error: "merge_review_reissue_exhausted", reissues });
    }
    const content = review.content as { ops: OpInput[] };
    return issueEnvelope(reply, projectId, {
      ops: content.ops,
      commitLabel: "Commit #2",
      approvalRef: { review_id: review.id, content_hash: review.content_hash },
      seqPolicy: "next_issued",
      reissueOf: env?.envelope_id,
    });
  });
}

/** GET /state additions (docs/PHASE6_DESIGN.md §5.4). */
export async function commit2State(repos: Repos, projectId: string): Promise<{
  mep_plan_ready: boolean;
  commit2_done: boolean;
  commit2: Record<string, unknown>;
}> {
  const chain = await repos.mergeChain(projectId);
  const interiorReady = await (async () => {
    if (!chain.interior || chain.interior.status !== "approved") return false;
    const confirmed = await repos.latestConfirmedBrief(projectId);
    return confirmed !== null &&
      (chain.interior.content as { brief_version?: number }).brief_version === confirmed.brief_version;
  })();
  const mepContent = chain.mep?.content as
    | { interior_review_id?: string; counts?: { blocking?: number } }
    | undefined;
  const mepReady =
    chain.mep?.status === "approved" &&
    interiorReady &&
    mepContent?.interior_review_id === chain.interior?.id &&
    (mepContent?.counts?.blocking ?? 1) === 0;
  const latest = chain.latest;
  const latestContent = latest?.content as { iteration?: number; iterations_used?: number } | undefined;
  const used = latestContent?.iterations_used ?? 0;
  const env = chain.envelope;
  const anyMerge = await repos.latestReviewOfKind(projectId, "commit2_merge");
  return {
    mep_plan_ready: mepReady,
    commit2_done: await repos.hasSnapshot(projectId, "commit2"),
    commit2: {
      chain:
        chain.interior && chain.mep
          ? { interior_review_id: chain.interior.id, mep_review_id: chain.mep.id }
          : null,
      iteration: latestContent?.iteration ?? null,
      iterations_used: used,
      budget_limit: MERGE_BUDGET,
      budget_remaining: Math.max(0, MERGE_BUDGET - used),
      merge_review_id: latest?.id ?? null,
      merge_status: latest ? latest.status : "none",
      envelope_status: env?.status ?? null,
      clash_pairs: env ? envelopeClashPairs(env) : null,
      last_errors: (env?.errors as unknown[] | null | undefined) ?? null,
      exhausted: chain.exhausted,
      failed: chain.failed,
      merge_current: anyMerge !== null && latest !== null && anyMerge.id === latest.id,
    },
  };
}
