// Phase 7 gateway flow (docs/PHASE7_DESIGN.md §1.3, §4): render-views issues the
// export_views envelope (plan / section / 3d_hidden @ 2048, NOT commit-class — nothing is
// written to the model) and opens a render job that correlates the executor's export_ready
// frames by order; compose-render reads the three blobs, calls the AIDM bridge (control
// maps + prompt + illustrative renders + SKU candidates) and files the render_review card;
// finish-selection turns the designer's structured selection into the set_parameter ops a
// finish_commit review carries (the render is illustrative, the selection is the data);
// issue-finish sends those ops VERBATIM under approval_ref as "Commit #3 finishes". Two
// human approvals; every rebuilt selection is a NEW card; failures are never auto-approved.
//
// There is deliberately no HTML finish-selection form: a per-room × per-surface picker needs
// client state and would duplicate the bridge's validation. The selection arrives over REST
// (HUB/portal); the human gate is the finish_commit card's Approve/Reject.
import { randomUUID } from "node:crypto";
import type { FastifyInstance, FastifyReply } from "fastify";
import { z } from "zod";
import { productsCatalog } from "@chapter/contracts";
import type { Config } from "../config.js";
import type { RenderJobRow, Repos, ReviewRow } from "../db/repos.js";
import type { OpInput } from "../envelope/builder.js";
import { checkParamAllowlist } from "../envelope/param-allowlist.js";
import { blobRefFor, sniffBlobType, type BlobStore } from "../blobs/store.js";
import { renderViews as bridgeRender, validateSelection as bridgeValidate } from "../render/bridge-client.js";
import { actorOrService, requireService } from "./auth.js";
import type { IssueSpec, Outcome } from "./commit2.js";

export const RENDER_VIEWS: { name: string; kind: "plan" | "section" | "3d_hidden"; px: number }[] = [
  { name: "plan", kind: "plan", px: 2048 },
  { name: "section", kind: "section", px: 2048 },
  { name: "3d_hidden", kind: "3d_hidden", px: 2048 },
];
export const EXPORT_LABEL = "Export views";
export const FINISH_LABEL = "Commit #3 finishes";
export const FINISH_REISSUE_CAP = 3;
export const FINISH_BODY_LIMIT = 256 * 1024;
const TRANSIENT_BRIDGE_ERRORS = new Set(["aidm_bridge_unreachable"]);
const FINISH_TIERS = new Set(["economy", "standard", "premium", "luxury"]);
const REF_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

export function productsCatalogVersion(): string {
  return productsCatalog.catalog_version;
}

/** finish_tier from a confirmed brief (default standard — the brief schema's default). */
export function finishTierOf(brief: unknown): string {
  const tier = (brief as { finish_tier?: unknown } | null)?.finish_tier;
  return typeof tier === "string" && FINISH_TIERS.has(tier) ? tier : "standard";
}

// The selection body is the bridge's shape; the gateway only bounds it (the semantics —
// unknown targets, tiers, surfaces, placeholders — belong to the bridge validator).
const item = z.record(z.string(), z.unknown());
export const selectionBody = z
  .object({
    rooms: z.array(item).max(60).default([]),
    casework: z.array(item).max(80).default([]),
    doors: z.array(item).max(120).default([]),
    plumbing_fixtures: z.array(item).max(60).default([]),
    overrides: z.array(item).max(64).default([]),
  })
  .strict();

interface RenderReviewContent {
  render_id: string;
  export_envelope_id: string;
  layout_snapshot: "commit1" | "commit2";
  renders: { name: string; provider: string; ref: string | null; status: string; blob_ref: string | null }[];
  finish_tier: string;
  brief_version: number;
  catalog_version: string;
}

type IssueOutcomeFn = (projectId: string, spec: IssueSpec) => Promise<Outcome>;
type IssueFn = (reply: FastifyReply, projectId: string, spec: IssueSpec) => Promise<FastifyReply>;

export function registerRenderRoutes(
  app: FastifyInstance,
  deps: { config: Config; repos: Repos; blobs: BlobStore | null },
  issue: { outcome: IssueOutcomeFn; reply: IssueFn },
): void {
  const { config, repos, blobs } = deps;
  const serviceAuth = requireService(config);
  const send = (reply: FastifyReply, out: Outcome): FastifyReply => reply.code(out.code).send(out.body);

  async function latestRenderReviewFor(projectId: string, renderId: string): Promise<ReviewRow | null> {
    const reviews = await repos.listReviewsOfKind(projectId, "render_review");
    const mine = reviews.filter((r) => (r.content as { render_id?: string }).render_id === renderId);
    return mine.length ? mine[mine.length - 1]! : null;
  }

  // ---- render-views: the export envelope + the job that receives its frames -------

  async function runRenderViews(projectId: string): Promise<Outcome> {
    if (!(await repos.getProject(projectId))) return { code: 404, body: { error: "unknown_project" } };
    if (!(await repos.hasSnapshot(projectId, "commit0"))) return { code: 409, body: { error: "commit0_not_done" } };
    if (!(await repos.hasSnapshot(projectId, "commit1"))) return { code: 409, body: { error: "commit1_not_done" } };
    const inflight = await repos.inflightEnvelope(projectId);
    if (inflight) {
      return inflight.commit_label === EXPORT_LABEL
        ? { code: 409, body: { error: "render_export_in_progress", envelope_id: inflight.envelope_id } }
        : { code: 409, body: { error: "envelope_in_flight", envelope_id: inflight.envelope_id } };
    }
    const renderId = randomUUID();
    const views = RENDER_VIEWS.map((v) => ({ ...v }));
    const out = await issue.outcome(projectId, {
      ops: [{ op: "export_views", args: { views } }],
      commitLabel: EXPORT_LABEL,
      beforeDispatch: async (envelopeId) => {
        await repos.createRenderJob({ renderId, projectId, envelopeId, views });
      },
    });
    if (out.code !== 202) return out;
    const issued = out.body as { envelope_id: string; seq: number };
    return { code: 202, body: { render_id: renderId, envelope_id: issued.envelope_id, seq: issued.seq } };
  }

  app.post("/projects/:id/render-views", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    return send(reply, await runRenderViews(projectId));
  });

  // ---- compose-render: blobs -> bridge -> render_review card ------------------------

  async function runCompose(projectId: string): Promise<Outcome> {
    if (!(await repos.getProject(projectId))) return { code: 404, body: { error: "unknown_project" } };
    if (!config.aidmBridgeUrl) return { code: 503, body: { error: "aidm_bridge_unavailable" } };
    if (!blobs) return { code: 503, body: { error: "blob_store_unavailable" } };
    const job = await repos.latestRenderJob(projectId);
    if (!job) return { code: 409, body: { error: "no_render_job" } };
    if (job.status === "failed") return { code: 409, body: { error: "render_export_failed", render_id: job.render_id } };
    if (job.status === "exporting") {
      return {
        code: 409,
        body: {
          error: "render_export_in_progress", render_id: job.render_id,
          attached: job.blob_refs.filter((r) => r !== null).length, expected: job.expected_views,
        },
      };
    }
    if (job.status === "composed") {
      // re-compose only after a rejection (a fresh card with fresh renders)
      const existing = await latestRenderReviewFor(projectId, job.render_id);
      if (existing?.status === "pending") return { code: 409, body: { error: "render_review_pending", review_id: existing.id } };
      if (existing?.status === "approved") return { code: 409, body: { error: "render_already_composed", review_id: existing.id } };
    }
    const pngs: Buffer[] = [];
    for (let i = 0; i < job.expected_views; i++) {
      const ref = job.blob_refs[i] ?? null;
      const bytes = ref ? await blobs.get(ref) : null;
      if (!ref || !bytes) return { code: 409, body: { error: "blob_missing", render_id: job.render_id, index: i, blob_ref: ref } };
      if (sniffBlobType(bytes) !== "png") return { code: 422, body: { error: "blob_not_png", blob_ref: ref } };
      pngs.push(bytes);
    }
    const brief = await repos.latestConfirmedBrief(projectId);
    if (!brief) return { code: 409, body: { error: "brief_not_confirmed" } };
    const finishTier = finishTierOf(brief.content);
    const snapshotLabel: "commit1" | "commit2" = (await repos.hasSnapshot(projectId, "commit2")) ? "commit2" : "commit1";
    const snapshot = (await repos.getSnapshot(projectId, snapshotLabel))!;
    const layout = snapshot.layout as {
      constraints?: { style_tags?: unknown };
      rooms?: { id: string; name: string; program: string }[];
    };
    const rawTags = layout.constraints?.style_tags;
    // style_tags are DATA (SI-7): bounded here, sanitised against the vocabulary by the bridge
    const styleTags = Array.isArray(rawTags)
      ? rawTags.filter((t): t is string => typeof t === "string" && t.length > 0).map((t) => t.slice(0, 40)).slice(0, 12)
      : [];
    const rooms = (layout.rooms ?? []).slice(0, 60).map((r) => ({ id: r.id, name: r.name, program: r.program }));

    const failure = async (content: Record<string, unknown>, hard: boolean): Promise<void> => {
      // one card per (job, error): a polling client never piles up duplicates
      const existing = await repos.pendingReviewOfKind(projectId, "render_failure");
      const dup = existing && (existing.content as { render_id?: string; error?: string });
      if (dup && dup.render_id === job.render_id && dup.error === content["error"]) return;
      await repos.createReview(
        projectId,
        "render_failure",
        { ...content, hard, render_id: job.render_id, export_envelope_id: job.envelope_id, brief_version: brief.brief_version },
        false,
      );
    };

    const outcome = await bridgeRender(config.aidmBridgeUrl, {
      project_id: projectId,
      render_id: job.render_id,
      views: job.views.map((v, i) => ({ name: v.name, kind: v.kind, px: v.px, png_base64: pngs[i]!.toString("base64") })),
      style_tags: styleTags,
      finish_tier: finishTier,
      rooms,
      allow_placeholders: config.allowPlaceholders,
    });
    if (!outcome.ok) {
      // unreachable / aborted says nothing about the export: retryable (hard=false); a
      // bridge verdict (png_invalid, render_internal, ...) is this job's fault
      const transient = TRANSIENT_BRIDGE_ERRORS.has(outcome.error);
      await failure({ reason: "render_error", error: outcome.error, message: outcome.message }, !transient);
      await repos.logEventDirect(projectId, "gateway", "render_failed", {
        render_id: job.render_id, error: outcome.error, message: outcome.message, raw_outputs: outcome.rawOutputs,
      });
      return { code: 422, body: { error: outcome.error, message: outcome.message } };
    }
    const result = outcome.result;

    // every PNG the bridge returned is stored by hash; the card carries refs only
    const store = async (b64: string): Promise<string | null> => {
      const bytes = Buffer.from(b64, "base64");
      if (bytes.length === 0 || sniffBlobType(bytes) !== "png") return null;
      const ref = blobRefFor(bytes);
      await blobs.put(ref, bytes);
      return ref;
    };
    const controlMaps: Record<string, unknown>[] = [];
    for (const m of result.control_maps) {
      const [canny, lines, preview] = await Promise.all([
        store(m.canny_png_base64), store(m.lines_png_base64), store(m.preview_png_base64),
      ]);
      if (!canny || !lines || !preview) {
        await failure({ reason: "render_error", error: "bridge_bad_png", message: `control map ${m.name} is not a PNG` }, true);
        return { code: 422, body: { error: "bridge_bad_png", message: `control map ${m.name} is not a PNG` } };
      }
      controlMaps.push({ name: m.name, kind: m.kind, canny_ref: canny, lines_ref: lines, preview_ref: preview, stats: m.stats });
    }
    const renders: RenderReviewContent["renders"] = [];
    for (const r of result.renders) {
      const blobRef = r.status === "ok" && r.png_base64 ? await store(r.png_base64) : null;
      if (r.status === "ok" && !blobRef) {
        await failure({ reason: "render_error", error: "bridge_bad_png", message: `render ${r.name} is not a PNG` }, true);
        return { code: 422, body: { error: "bridge_bad_png", message: `render ${r.name} is not a PNG` } };
      }
      renders.push({ name: r.name, provider: r.provider, ref: r.ref, status: r.status, blob_ref: blobRef });
    }
    const reviewItems = [...result.review_items];
    const bridgeCatalog = (result.diagnostics as { catalog_version?: unknown }).catalog_version;
    if (typeof bridgeCatalog === "string" && bridgeCatalog !== productsCatalogVersion()) {
      reviewItems.push({
        code: "catalog_version_skew", severity: "warning", refs: [bridgeCatalog, productsCatalogVersion()],
        message: "the bridge and the gateway read different product catalogs — redeploy before selecting finishes",
      });
    }
    const candidateCount = Object.values(result.candidates).reduce((n, list) => n + list.length, 0);
    const content = {
      render_id: job.render_id,
      export_envelope_id: job.envelope_id,
      layout_snapshot: snapshotLabel,
      control_maps: controlMaps,
      renders,
      prompt: result.prompt,
      candidates: result.candidates,
      finish_tier: finishTier,
      brief_version: brief.brief_version,
      review_items: reviewItems,
      catalog_version: productsCatalogVersion(),
      source_blob_refs: job.blob_refs,
      diagnostics: result.diagnostics,
      counts: {
        views: controlMaps.length,
        renders_ok: renders.filter((r) => r.status === "ok").length,
        candidates: candidateCount,
        review_items: reviewItems.length,
        tags_used: result.prompt.tags_used.length,
        tags_dropped: result.prompt.tags_dropped.length,
      },
    };
    const review = await repos.createReview(projectId, "render_review", content, config.autoApprove);
    await repos.setRenderJobStatus(job.render_id, "composed");
    return {
      code: 201,
      body: { review_id: review.id, content_hash: review.content_hash, status: review.status, counts: content.counts },
    };
  }

  app.post("/projects/:id/compose-render", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    return send(reply, await runCompose(projectId));
  });

  // ---- finish-selection: the structured selection -> finish_commit card -----------

  app.post(
    "/projects/:id/finish-selection",
    { preHandler: actorOrService(config), bodyLimit: FINISH_BODY_LIMIT },
    async (req, reply) => {
      const projectId = (req.params as { id: string }).id;
      if (!(await repos.getProject(projectId))) return reply.code(404).send({ error: "unknown_project" });
      if (!config.aidmBridgeUrl) return reply.code(503).send({ error: "aidm_bridge_unavailable" });
      const render = await repos.latestReviewOfKind(projectId, "render_review");
      if (!render) return reply.code(409).send({ error: "no_render_review" });
      if (render.status !== "approved") {
        return reply.code(409).send({ error: "render_not_approved", status: render.status });
      }
      const rc = render.content as RenderReviewContent;
      const job = await repos.latestRenderJob(projectId);
      const confirmed = await repos.latestConfirmedBrief(projectId);
      // the approval must be about the CURRENT export and the CURRENT confirmed brief
      if (!job || job.render_id !== rc.render_id || !confirmed || confirmed.brief_version !== rc.brief_version) {
        return reply.code(409).send({ error: "render_review_stale", review_id: render.id });
      }
      if (await repos.finishSelectionForProject(projectId)) {
        return reply.code(409).send({ error: "finish_already_done" });
      }
      const pending = await repos.pendingReviewOfKind(projectId, "finish_commit");
      if (pending) return reply.code(409).send({ error: "finish_review_pending", review_id: pending.id });
      const selection = selectionBody.parse(req.body ?? {});

      const snapshotLabel = rc.layout_snapshot === "commit2" && (await repos.hasSnapshot(projectId, "commit2")) ? "commit2" : "commit1";
      const snapshot = await repos.getSnapshot(projectId, snapshotLabel);
      if (!snapshot) return reply.code(409).send({ error: "commit1_not_done" });
      const idMap = await repos.idMapEntries(projectId);
      const okRender = rc.renders.find((r) => r.status === "ok" && r.ref && REF_RE.test(r.ref));
      const renderRef = okRender?.ref ?? null;
      const outcome = await bridgeValidate(config.aidmBridgeUrl, {
        project_id: projectId,
        layout: snapshot.layout,
        id_map_ids: Object.keys(idMap).sort(),
        finish_tier: rc.finish_tier,
        catalog_version: productsCatalogVersion(),
        render_ref: renderRef,
        selection,
        allow_placeholders: config.allowPlaceholders,
      });
      if (!outcome.ok) {
        await repos.logEventDirect(projectId, "gateway", "finish_validate_failed", {
          render_review_id: render.id, error: outcome.error, message: outcome.message, raw_outputs: outcome.rawOutputs,
        });
        return reply.code(422).send({ error: outcome.error, message: outcome.message });
      }
      const result = outcome.result;
      if (result.blocking.length) {
        // no card: the caller fixes the selection and re-posts
        await repos.logEventDirect(projectId, "gateway", "finish_validate_failed", {
          render_review_id: render.id, error: "finish_selection_blocked", blocking: result.blocking,
        });
        return reply.code(422).send({
          error: "finish_selection_blocked",
          blocking: result.blocking,
          items: result.review_items.filter((i) => i.severity === "blocking"),
        });
      }
      // SI-4: the gateway polices the bridge's emission before anything is reviewable
      const problem = checkParamAllowlist(result.ops as OpInput[]);
      if (problem) {
        await repos.logEventDirect(projectId, "gateway", "finish_validate_failed", {
          render_review_id: render.id, error: "param_not_allowlisted", detail: problem,
        });
        return reply.code(422).send({ error: "param_not_allowlisted", detail: problem });
      }
      if (result.ops.length === 0) {
        return reply.code(422).send({ error: "finish_selection_empty", message: "the selection produces no set_parameter ops" });
      }
      const content = {
        selection,
        ops: result.ops,
        catalog_version: productsCatalogVersion(),
        render_ref: renderRef,
        render_blob_ref: okRender?.blob_ref ?? null,
        render_review_id: render.id,
        render_id: rc.render_id,
        finish_tier: rc.finish_tier,
        brief_version: rc.brief_version,
        review_items: result.review_items,
        diagnostics: result.diagnostics,
        counts: result.diagnostics.counts,
      };
      let review: ReviewRow;
      try {
        review = await repos.createReview(projectId, "finish_commit", content, config.autoApprove);
      } catch (err) {
        if (String(err).includes("reviews_one_pending_finish_commit")) {
          return reply.code(409).send({ error: "finish_review_pending" });
        }
        throw err;
      }
      return reply.code(201).send({
        review_id: review.id, content_hash: review.content_hash, status: review.status, counts: content.counts,
      });
    },
  );

  // ---- issue-finish: Commit #3 finishes, ops verbatim under approval_ref ------------

  app.post("/projects/:id/issue-finish", { preHandler: serviceAuth }, async (req, reply) => {
    const projectId = (req.params as { id: string }).id;
    if (!(await repos.getProject(projectId))) return reply.code(404).send({ error: "unknown_project" });
    const review = await repos.latestReviewOfKind(projectId, "finish_commit");
    if (!review) return reply.code(409).send({ error: "no_finish_review" });
    if (review.status !== "approved") {
      return reply.code(409).send({ error: "finish_review_not_approved", status: review.status });
    }
    if (await repos.finishSelectionForProject(projectId)) {
      return reply.code(409).send({ error: "finish_already_done" });
    }
    const env = await repos.latestEnvelopeForReview(review.id);
    if (env && (env.status === "issued" || env.status === "ack_accepted")) {
      return reply.code(409).send({ error: "envelope_in_flight", envelope_id: env.envelope_id });
    }
    const reissues = await repos.envelopeCountForReview(review.id);
    if (reissues >= FINISH_REISSUE_CAP) {
      // three transient failures of the same selection: spent (hard) — a new selection
      // restarts; the card is filed once
      const existing = await repos.pendingReviewOfKind(projectId, "finish_failure");
      const dup = existing && (existing.content as { finish_review_id?: string; reason?: string });
      if (!(dup && dup.finish_review_id === review.id && dup.reason === "finish_reissue_exhausted")) {
        await repos.createReview(
          projectId,
          "finish_failure",
          { reason: "finish_reissue_exhausted", hard: true, finish_review_id: review.id, reissues },
          false,
        );
      }
      return reply.code(409).send({ error: "finish_reissue_exhausted", reissues });
    }
    if (await repos.finishHardFailure(projectId, review.id)) {
      return reply.code(409).send({ error: "finish_review_failed", review_id: review.id });
    }
    const content = review.content as { ops: OpInput[] };
    return issue.reply(reply, projectId, {
      ops: content.ops,
      commitLabel: FINISH_LABEL,
      approvalRef: { review_id: review.id, content_hash: review.content_hash },
      reissueOf: env?.envelope_id,
    });
  });
}

/** GET /state additions (docs/PHASE7_DESIGN.md §4). */
export async function renderState(repos: Repos, projectId: string): Promise<{
  render: Record<string, unknown> | null;
  render_exported: boolean;
  render_review_ready: boolean;
  finish: Record<string, unknown> | null;
  finish_ready: boolean;
  finish_done: boolean;
}> {
  const job: RenderJobRow | null = await repos.latestRenderJob(projectId);
  const renderReview = await repos.latestReviewOfKind(projectId, "render_review");
  const rc = renderReview?.content as RenderReviewContent | undefined;
  const confirmed = await repos.latestConfirmedBrief(projectId);
  const envelope = job ? await repos.getEnvelope(job.envelope_id) : null;
  const renderReviewReady =
    renderReview?.status === "approved" &&
    job !== null &&
    rc?.render_id === job.render_id &&
    confirmed !== null &&
    rc?.brief_version === confirmed.brief_version;
  const finish = await repos.latestReviewOfKind(projectId, "finish_commit");
  const done = await repos.finishSelectionForProject(projectId);
  const finishEnv = finish ? await repos.latestEnvelopeForReview(finish.id) : null;
  const hardFailed = finish ? (await repos.finishHardFailure(projectId, finish.id)) !== null : false;
  return {
    render: job
      ? {
          render_id: job.render_id,
          status: job.status,
          envelope_id: job.envelope_id,
          envelope_status: envelope?.status ?? null,
          expected_views: job.expected_views,
          blob_refs: job.blob_refs.filter((r) => r !== null).length,
          render_review_id: renderReview && rc?.render_id === job.render_id ? renderReview.id : null,
          render_review_status: renderReview && rc?.render_id === job.render_id ? renderReview.status : null,
        }
      : null,
    render_exported: job !== null && (job.status === "exported" || job.status === "composed"),
    render_review_ready: renderReviewReady === true,
    finish: finish
      ? {
          finish_review_id: finish.id,
          status: finish.status,
          envelope_status: finishEnv?.status ?? null,
          catalog_version: (finish.content as { catalog_version?: string }).catalog_version ?? null,
          reissues: await repos.envelopeCountForReview(finish.id),
          hard_failed: hardFailed,
        }
      : null,
    finish_ready: finish !== null && finish.status === "approved" && done === null && !hardFailed,
    finish_done: done !== null,
  };
}
