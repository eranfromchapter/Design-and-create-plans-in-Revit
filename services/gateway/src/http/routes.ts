import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { z } from "zod";
import type { Config } from "../config.js";
import type { Repos } from "../db/repos.js";
import type { GatewayCore } from "../core.js";
import { buildEnvelope } from "../envelope/builder.js";
import { newProjectKeypair } from "../crypto/keystore.js";
import { requireActor, requireService, resolveActor } from "./auth.js";
import { renderReviewsPage } from "../ui/reviews.js";

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
const decideBody = z.object({ note: z.string().max(2000).optional() }).default({});

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

  app.post("/projects/:id/envelopes", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    const project = await repos.getProject(projectId);
    if (!project) return reply.code(404).send({ error: "unknown_project" });

    // Drift gate: a dirty project (or one with a pending drift review) issues nothing
    // until a human clears it (PLAN.md Part B "Trust and drift").
    if (project.drift_state === "dirty") {
      return reply.code(409).send({ error: "drift_review_pending" });
    }

    const session = core.executorReady(projectId);
    if (!session) return reply.code(409).send({ error: "no_executor_connected" });

    const body = envelopeBody.parse(req.body);
    const seq = (await repos.lastCommittedSeq(projectId)) + 1;
    const built = buildEnvelope(
      {
        projectId,
        workstationId: (await currentWorkstation(core, projectId)) ?? "",
        seq,
        ops: body.ops as { op: string; args: Record<string, unknown> }[],
        ttlS: body.ttl_s ?? config.envelopeTtlDefaultS,
        commitLabel: body.commit_label,
        approvalRef: body.approval_ref,
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
        workstationId: (await currentWorkstation(core, projectId)) ?? "",
        seq,
        payload: built.payload,
        sig: built.sig,
        commitLabel: body.commit_label,
        approvalRef: body.approval_ref,
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
      const review = await repos.decideReview(reviewId, decision === "approve", actor, body.note);
      if (!review) {
        const exists = await repos.getReview(reviewId);
        return reply.code(exists ? 409 : 404).send({ error: exists ? "already_decided" : "unknown_review" });
      }
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
    const review = await repos.decideReview(id, decision === "approve", actor);
    const token = (req.query as Record<string, string | undefined>)["actor_token"] ?? "";
    const projectId =
      review?.project_id ?? (await repos.getReview(id))?.project_id ?? "";
    return reply.redirect(`/ui/projects/${projectId}/reviews?actor_token=${encodeURIComponent(token)}`);
  });
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

async function currentWorkstation(core: GatewayCore, projectId: string): Promise<string | null> {
  return core.workstationFor(projectId);
}
