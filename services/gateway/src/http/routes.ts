import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { z } from "zod";
import type { Config } from "../config.js";
import type { Repos, ReviewRow } from "../db/repos.js";
import type { GatewayCore } from "../core.js";
import { buildEnvelope, type OpInput } from "../envelope/builder.js";
import { newProjectKeypair } from "../crypto/keystore.js";
import { requireActor, requireService, resolveActor } from "./auth.js";
import { renderReviewsPage } from "../ui/reviews.js";
import { convertScanBundle, type ReviewPayload } from "../scan/converter-client.js";
import { opsFromScanLayout } from "../scan/ops.js";
import { extractBrief } from "../brief/extractor-client.js";
import { compileLayout } from "../layout/compiler-client.js";
import { commit0LayoutFromReview } from "../layout/snapshot.js";

const createProjectBody = z.object({ name: z.string().min(1).max(200) });
const enrollBody = z.object({
  workstation_id: z.string().regex(/^[a-z0-9][a-z0-9_-]{0,63}$/),
});
const envelopeBody = z.object({
  ops: z.array(z.object({ op: z.string().min(1), args: z.record(z.string(), z.unknown()) })).min(1).max(1000),
  commit_label: z.string().max(80).optional(),
  approval_ref: z
    .object({ review_id: z.uuid(), content_hash: z.string().regex(/^[0-9a-f]{64}$/) })
    .optional(),
  ttl_s: z.number().int().min(10).max(3600).optional(),
});
const confirmationsSchema = z.object({
  unit: z.enum(["mm", "inch", "ft", "cm", "m"]).optional(),
  ceiling_height_mm: z.number().min(2100).max(6000).optional(), // create_wall bounds
});
const decideBody = z
  .object({
    note: z.string().max(2000).optional(),
    confirmations: confirmationsSchema.optional(),
  })
  .default({});
const scanBundleBody = z.object({
  dxf_base64: z.string().min(1),
  cloud_ref: z.string().regex(/^[a-z0-9][a-z0-9_-]{0,63}$/).optional(),
  level_name: z.string().min(1).max(80).optional(),
  ceiling_default_mm: z.number().min(2100).max(6000).optional(),
  unit_override: z.enum(["mm", "inch", "ft", "cm", "m"]).optional(),
});
const transcriptsBody = z.object({
  sessions: z
    .array(z.object({ session_id: z.string().min(1).max(120), text: z.string().min(1) }))
    .min(1)
    .max(20),
  client_names: z.array(z.string().min(1).max(120)).max(10).optional(),
});

export function registerRoutes(
  app: FastifyInstance,
  deps: { config: Config; repos: Repos; core: GatewayCore },
): void {
  const { config, repos, core } = deps;
  const serviceAuth = requireService(config);
  const actorAuth = requireActor(config);

  app.get("/healthz", async () => ({ ok: true }));

  app.post("/projects", { preHandler: serviceAuth }, async (req, reply) => {
    const body = createProjectBody.parse(req.body);
    const keypair = newProjectKeypair(config.masterKey);
    const project = await repos.createProject(body.name, keypair.publicKeyHex, keypair.seedEnc);
    return reply.code(201).send({ id: project.id, signing_public_key: project.signing_public_key });
  });

  app.post("/projects/:id/workstations", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    if (!(await repos.getProject(projectId))) return reply.code(404).send({ error: "unknown_project" });
    const body = enrollBody.parse(req.body);
    const token = await repos.enrollWorkstation(projectId, body.workstation_id);
    // The token is returned exactly once; only its hash is stored.
    return reply.code(201).send({ workstation_id: body.workstation_id, token });
  });

  /** Shared envelope-issuing path: drift gate -> executor -> build/sign -> persist
   *  (one-in-flight) -> dispatch. Used by POST /envelopes and POST /issue-commit0. */
  async function issueEnvelope(
    reply: FastifyReply,
    projectId: string,
    spec: {
      ops: OpInput[];
      ttlS?: number;
      commitLabel?: string;
      approvalRef?: { review_id: string; content_hash: string };
    },
  ): Promise<FastifyReply> {
    const project = await repos.getProject(projectId);
    if (!project) return reply.code(404).send({ error: "unknown_project" });

    // Drift gate: a dirty project (or one with a pending drift review) issues nothing
    // until a human clears it (PLAN.md Part B "Trust and drift").
    if (project.drift_state === "dirty") {
      return reply.code(409).send({ error: "drift_review_pending" });
    }

    if (!core.executorReady(projectId)) {
      return reply.code(409).send({ error: "no_executor_connected" });
    }

    const workstationId = core.workstationFor(projectId) ?? "";
    const seq = (await repos.lastCommittedSeq(projectId)) + 1;
    const built = buildEnvelope(
      {
        projectId,
        workstationId,
        seq,
        ops: spec.ops,
        ttlS: spec.ttlS ?? config.envelopeTtlDefaultS,
        commitLabel: spec.commitLabel,
        approvalRef: spec.approvalRef,
        issuedAt: new Date(),
      },
      project.signing_seed_enc,
      config.masterKey,
    );
    if (!built.ok) return reply.code(422).send({ error: "invalid_ops", detail: built.error });

    try {
      await repos.insertIssuedEnvelope({
        envelopeId: built.envelopeId,
        projectId,
        workstationId,
        seq,
        payload: built.payload,
        sig: built.sig,
        commitLabel: spec.commitLabel,
        approvalRef: spec.approvalRef,
        issuedAt: built.issuedAt,
      });
    } catch (err) {
      if (String(err).includes("envelopes_one_inflight")) {
        return reply.code(409).send({ error: "envelope_in_flight" });
      }
      throw err;
    }

    if (!core.sendEnvelope(projectId, built.payload, built.sig)) {
      return reply.code(409).send({ error: "no_executor_connected" });
    }
    return reply.code(202).send({ envelope_id: built.envelopeId, seq });
  }

  app.post("/projects/:id/envelopes", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const body = envelopeBody.parse(req.body);
    return issueEnvelope(reply, projectId, {
      ops: body.ops as OpInput[],
      ttlS: body.ttl_s,
      commitLabel: body.commit_label,
      approvalRef: body.approval_ref,
    });
  });

  // ---- Lane A scan flow (Phase 2): upload -> review -> approve -> Commit #0 ----

  app.post(
    "/projects/:id/scan-bundles",
    // real base64 DXFs overflow Fastify's 1MB default body cap
    { preHandler: serviceAuth, bodyLimit: 32 * 1024 * 1024 },
    async (req, reply) => {
      const projectId = (req.params as { id: string }).id;
      const project = await repos.getProject(projectId);
      if (!project) return reply.code(404).send({ error: "unknown_project" });
      if (project.commit0_done) return reply.code(409).send({ error: "commit0_already_done" });
      if (!config.scanConverterUrl) {
        return reply.code(503).send({ error: "scan_converter_unavailable" });
      }

      const body = scanBundleBody.parse(req.body);
      const outcome = await convertScanBundle(config.scanConverterUrl, {
        dxf_base64: body.dxf_base64,
        project_id: projectId,
        level_name: body.level_name,
        ceiling_default_mm: body.ceiling_default_mm,
        unit_override: body.unit_override,
        cloud_ref: body.cloud_ref,
      });
      if (!outcome.ok) {
        return reply.code(422).send({ error: outcome.error, message: outcome.message });
      }

      // Pipeline gate: honors AUTO_APPROVE (CI-only) — unlike drift reviews.
      const review = await repos.createReview(
        projectId, "scan_commit0", outcome.reviewPayload, config.autoApprove,
      );
      return reply.code(201).send({
        review_id: review.id,
        content_hash: review.content_hash,
        status: review.status,
        counts: outcome.reviewPayload.counts,
      });
    },
  );

  app.post("/projects/:id/issue-commit0", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const project = await repos.getProject(projectId);
    if (!project) return reply.code(404).send({ error: "unknown_project" });
    if (project.commit0_done) return reply.code(409).send({ error: "commit0_already_done" });

    const review = await repos.latestReviewOfKind(projectId, "scan_commit0");
    if (!review) return reply.code(409).send({ error: "no_scan_review" });
    if (review.status !== "approved") {
      return reply.code(409).send({ error: "scan_review_not_approved", status: review.status });
    }

    const content = review.content as ReviewPayload;
    // shared derivation with the frozen snapshot recordCommitResult writes, so
    // the snapshot always matches what was committed (heights = confirmed ceiling)
    const { ceilingMm } = commit0LayoutFromReview(review);
    const ops = opsFromScanLayout(content.layout, {
      ceilingMm,
      cloudRef: content.layout.meta.scan?.cloud_ref,
    });
    return issueEnvelope(reply, projectId, {
      ops,
      commitLabel: "Commit #0",
      approvalRef: { review_id: review.id, content_hash: review.content_hash },
    });
  });

  // ---- Phase 4 layout flow: compile -> layout_commit1 review -> Commit #1 ----

  app.post("/projects/:id/compile-layout", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    if (!(await repos.getProject(projectId))) {
      return reply.code(404).send({ error: "unknown_project" });
    }
    if (!config.layoutCompilerUrl) {
      return reply.code(503).send({ error: "layout_compiler_unavailable" });
    }
    // the frozen Commit #0 snapshot is the diff baseline — no snapshot, no compile
    const snapshot = await repos.getSnapshot(projectId, "commit0");
    if (!snapshot) return reply.code(409).send({ error: "commit0_not_done" });
    if (await repos.hasSnapshot(projectId, "commit1")) {
      return reply.code(409).send({ error: "commit1_already_done" });
    }
    const brief = await repos.latestBrief(projectId);
    if (!brief) return reply.code(409).send({ error: "no_brief" });
    if (!brief.confirmed_by_client) {
      return reply.code(409).send({ error: "brief_not_confirmed" });
    }

    const outcome = await compileLayout(config.layoutCompilerUrl, {
      project_id: projectId,
      brief: brief.content,
      existing_layout: snapshot.layout,
    });
    if (!outcome.ok) {
      // REVIEW on failure (PLAN.md Phase 4): informational card, never
      // auto-approved — AUTO_APPROVE must not wave a failed compile through
      await repos.createReview(
        projectId,
        "layout_failure",
        { error: outcome.error, message: outcome.message, brief_version: brief.brief_version },
        false,
      );
      await repos.logEventDirect(projectId, "gateway", "layout_compile_failed", {
        error: outcome.error,
        message: outcome.message,
        raw_outputs: outcome.rawOutputs,
      });
      return reply.code(422).send({ error: outcome.error, message: outcome.message });
    }

    const { result } = outcome;
    // everything the human approves rides in the review content: approval_ref's
    // content_hash then covers the exact ops issue-commit1 will send verbatim
    const review = await repos.createReview(
      projectId,
      "layout_commit1",
      {
        layout: result.layout,
        ops: result.ops,
        demolition_list: result.demolition,
        svgs: result.svgs,
        diagnostics: result.diagnostics,
        brief_version: brief.brief_version,
        counts: {
          walls: result.layout.walls.length,
          doors: result.layout.doors.length,
          windows: result.layout.windows.length,
          rooms: result.layout.rooms?.length ?? 0,
          demolished: result.demolition.length,
        },
      },
      config.autoApprove,
    );
    return reply.code(201).send({
      review_id: review.id,
      content_hash: review.content_hash,
      status: review.status,
      counts: (review.content as { counts: unknown }).counts,
    });
  });

  app.post("/projects/:id/issue-commit1", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const project = await repos.getProject(projectId);
    if (!project) return reply.code(404).send({ error: "unknown_project" });
    if (!project.commit0_done) return reply.code(409).send({ error: "commit0_not_done" });
    if (await repos.hasSnapshot(projectId, "commit1")) {
      return reply.code(409).send({ error: "commit1_already_done" });
    }

    const review = await repos.latestReviewOfKind(projectId, "layout_commit1");
    if (!review) return reply.code(409).send({ error: "no_layout_review" });
    if (review.status !== "approved") {
      return reply.code(409).send({ error: "layout_review_not_approved", status: review.status });
    }

    // ops verbatim from the approved review content — the envelope builder
    // re-validates each against the registry before signing (SI-2)
    const content = review.content as { ops: OpInput[] };
    return issueEnvelope(reply, projectId, {
      ops: content.ops,
      commitLabel: "Commit #1",
      approvalRef: { review_id: review.id, content_hash: review.content_hash },
    });
  });

  // ---- Phase 3 brief flow: transcripts -> versioned brief -> client confirmation ----

  app.post(
    "/projects/:id/transcripts",
    // multiple long session transcripts can overflow Fastify's 1MB default
    { preHandler: serviceAuth, bodyLimit: 8 * 1024 * 1024 },
    async (req, reply) => {
      const projectId = (req.params as { id: string }).id;
      if (!(await repos.getProject(projectId))) {
        return reply.code(404).send({ error: "unknown_project" });
      }
      if (!config.briefExtractorUrl) {
        return reply.code(503).send({ error: "brief_extractor_unavailable" });
      }

      const body = transcriptsBody.parse(req.body);
      const prior = await repos.latestBrief(projectId);
      const outcome = await extractBrief(config.briefExtractorUrl, {
        project_id: projectId,
        brief_version: (prior?.brief_version ?? 0) + 1,
        sessions: body.sessions,
        client_names: body.client_names,
        prior_brief: prior?.content,
      });
      if (!outcome.ok) {
        // hard fail: the extractor's raw outputs are stored in the event log
        await repos.logEventDirect(projectId, "gateway", "brief_extraction_failed", {
          error: outcome.error,
          message: outcome.message,
          raw_outputs: outcome.rawOutputs,
        });
        return reply.code(422).send({ error: outcome.error, message: outcome.message });
      }

      // pipeline gate: honors AUTO_APPROVE (CI-only); the human path is the
      // client_brief review card, whose approval marks the brief confirmed
      const { brief, review } = await repos.createBriefWithReview(
        projectId, outcome.brief, outcome.diagnostics, config.autoApprove,
      );
      return reply.code(201).send({
        brief_id: brief.id,
        brief_version: brief.brief_version,
        review_id: review.id,
        status: review.status,
        contradiction_count: outcome.diagnostics.contradiction_count,
      });
    },
  );

  app.get("/projects/:id/brief", { preHandler: actorOrService(config) }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    if (!(await repos.getProject(projectId))) {
      return reply.code(404).send({ error: "unknown_project" });
    }
    const brief = await repos.latestBrief(projectId);
    if (!brief) return reply.code(404).send({ error: "no_brief" });
    return {
      brief_id: brief.id,
      brief_version: brief.brief_version,
      confirmed_by_client: brief.confirmed_by_client,
      brief: brief.content,
      created_at: brief.created_at.toISOString(),
    };
  });

  app.get("/projects/:id/state", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const project = await repos.getProject(projectId);
    if (!project) return reply.code(404).send({ error: "unknown_project" });
    return {
      project_id: project.id,
      name: project.name,
      drift_state: project.drift_state,
      commit0_done: project.commit0_done,
      commit1_done: await repos.hasSnapshot(projectId, "commit1"),
      executor_connected: core.executorReady(projectId),
      last_committed_seq: await repos.lastCommittedSeq(projectId),
      id_map: await repos.idMapEntries(projectId),
      id_map_hash: await repos.gatewayIdMapHash(projectId),
      pending_reviews: await repos.pendingReviewCount(projectId),
      recent_envelopes: (await repos.recentEnvelopes(projectId)).map((e) => ({
        envelope_id: e.envelope_id,
        seq: e.seq,
        status: e.status,
        reject_reason: e.reject_reason,
      })),
    };
  });

  app.get("/projects/:id/reviews", { preHandler: actorOrService(config) }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    if (!(await repos.getProject(projectId))) return reply.code(404).send({ error: "unknown_project" });
    return { reviews: await repos.listReviews(projectId) };
  });

  for (const decision of ["approve", "reject"] as const) {
    app.post(`/reviews/:id/${decision}`, { preHandler: actorAuth }, async (req, reply) => {
      const reviewId = (req.params as { id: string }).id;
      const actor = resolveActor(config, req)!;
      const body = decideBody.parse(req.body ?? {});

      const existing = await repos.getReview(reviewId);
      if (!existing) return reply.code(404).send({ error: "unknown_review" });
      if (decision === "approve") {
        const problem = confirmationProblem(existing, body.confirmations);
        if (problem) return reply.code(422).send(problem);
      }
      const review = await repos.decideReview(
        reviewId,
        decision === "approve",
        actor,
        body.note,
        body.confirmations ? { confirmations: body.confirmations } : undefined,
      );
      if (!review) return reply.code(409).send({ error: "already_decided" });
      return { review_id: review.id, status: review.status, decided_by: review.decided_by };
    });
  }

  // Minimal human review surface (decided at the Phase 0 gate): server-rendered,
  // form-POST approve/reject, no client JS. HUB integration is a later decision.
  app.get("/ui/projects/:id/reviews", { preHandler: actorAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const project = await repos.getProject(projectId);
    if (!project) return reply.code(404).send({ error: "unknown_project" });
    const token = (req.query as Record<string, string | undefined>)["actor_token"] ?? "";
    const html = renderReviewsPage(project.name, projectId, await repos.listReviews(projectId), token);
    return reply.type("text/html; charset=utf-8").send(html);
  });

  app.post("/ui/reviews/:id/:decision", { preHandler: actorAuth }, async (req, reply) => {
    const { id, decision } = req.params as { id: string; decision: string };
    if (decision !== "approve" && decision !== "reject") {
      return reply.code(404).send({ error: "unknown_action" });
    }
    const actor = resolveActor(config, req)!;

    // form fields (urlencoded) -> confirmations, validated exactly like the REST path
    const form = (req.body ?? {}) as Record<string, string | undefined>;
    let confirmations: { unit?: "mm" | "inch" | "ft" | "cm" | "m"; ceiling_height_mm?: number } | undefined;
    if (form["ceiling_height_mm"] || form["unit"]) {
      const parsed = confirmationsSchema.safeParse({
        unit: form["unit"] || undefined,
        ceiling_height_mm: form["ceiling_height_mm"]
          ? Number(form["ceiling_height_mm"])
          : undefined,
      });
      if (!parsed.success) return reply.code(422).send({ error: "bad_confirmations" });
      confirmations = parsed.data;
    }
    if (decision === "approve") {
      const existing = await repos.getReview(id);
      if (!existing) return reply.code(404).send({ error: "unknown_review" });
      const problem = confirmationProblem(existing, confirmations);
      if (problem) return reply.code(422).send(problem);
    }

    const review = await repos.decideReview(
      id, decision === "approve", actor, undefined,
      confirmations ? { confirmations } : undefined,
    );
    const token = (req.query as Record<string, string | undefined>)["actor_token"] ?? "";
    const projectId =
      review?.project_id ?? (await repos.getReview(id))?.project_id ?? "";
    return reply.redirect(`/ui/projects/${projectId}/reviews?actor_token=${encodeURIComponent(token)}`);
  });
}

/** Approval-time confirmation rules for scan_commit0 reviews (PLAN.md Phase 2):
 *  the ceiling height must be confirmed; the unit must be confirmed when the
 *  converter used the heuristic; a DIFFERENT unit is confirm-or-reupload, never a
 *  gateway-side rescale (reject, then re-POST /scan-bundles with unit_override). */
function confirmationProblem(
  review: ReviewRow,
  confirmations?: { unit?: string; ceiling_height_mm?: number },
): { error: string; message: string } | null {
  if (review.kind !== "scan_commit0") return null;
  const unit = (review.content as ReviewPayload).unit;
  if (confirmations?.ceiling_height_mm === undefined) {
    return {
      error: "confirmation_required",
      message: "approving a scan_commit0 review requires confirmations.ceiling_height_mm",
    };
  }
  if (unit.confirmation_required && confirmations.unit === undefined) {
    return {
      error: "confirmation_required",
      message: `unit was heuristically detected (${unit.detected}); confirmations.unit is required`,
    };
  }
  if (confirmations.unit !== undefined && confirmations.unit !== unit.detected) {
    return {
      error: "unit_mismatch",
      message:
        `confirmed unit ${confirmations.unit} != detected ${unit.detected}; ` +
        "reject this review and re-upload the bundle with unit_override",
    };
  }
  return null;
}

function actorOrService(config: Config) {
  const service = requireService(config);
  const actor = requireActor(config);
  return async (req: FastifyRequest, reply: FastifyReply): Promise<void> => {
    // accept either credential kind; try actor first so review pages work with actor tokens
    if (resolveActor(config, req)) return;
    if (req.headers.authorization) return service(req, reply);
    return actor(req, reply);
  };
}

