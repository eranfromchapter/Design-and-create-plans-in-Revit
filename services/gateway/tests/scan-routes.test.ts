// DB-backed Phase 2 scan flow: upload -> scan_commit0 review -> approve with
// confirmations -> issue-commit0 preconditions. The converter is a local stub
// HTTP server speaking the real /convert contract, so the gateway's client code
// and error passthrough are what's tested. Requires DATABASE_URL.
import { createServer, type Server } from "node:http";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import type { InjectOptions } from "fastify";
import { loadConfig, type Config } from "../src/config.js";
import { buildGateway, type Gateway } from "../src/app.js";

const DATABASE_URL = process.env["DATABASE_URL"];
const SERVICE = "service-token-0123456789";
const ACTOR = "actor-token-eran";

const GOLDEN_LAYOUT = JSON.parse(
  readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "fixtures", "layouts", "2br_golden.json"),
    "utf8",
  ),
) as Record<string, unknown>;

function reviewPayload(confirmationRequired: boolean): Record<string, unknown> {
  return {
    layout: GOLDEN_LAYOUT,
    unit: {
      detected: "mm",
      insunits: confirmationRequired ? 0 : 4,
      source: confirmationRequired ? "heuristic" : "insunits",
      confirmation_required: confirmationRequired,
      bbox_span_raw: 11400,
      bbox_span_mm: 11400,
    },
    height_assumption_mm: 2700,
    assumptions: [{ field: "wall_height", value: 2700, note: "confirm ceiling" }],
    flags: [],
    low_confidence: [],
    room_labels: [],
    counts: { walls: 17, doors: 5, windows: 3 },
  };
}

// scripted converter stub: each POST /convert shifts the next canned response
type Canned = { status: number; body: unknown };
const cannedQueue: Canned[] = [];
let converter: Server;
let converterUrl: string;

describe.skipIf(!DATABASE_URL)("gateway scan flow (DB-backed)", () => {
  let gw: Gateway;
  let config: Config;

  beforeAll(async () => {
    converter = createServer((req, res) => {
      let raw = "";
      req.on("data", (c) => (raw += c));
      req.on("end", () => {
        const canned = cannedQueue.shift() ?? {
          status: 200,
          body: { layout: GOLDEN_LAYOUT, review_payload: reviewPayload(false) },
        };
        res.writeHead(canned.status, { "content-type": "application/json" });
        res.end(JSON.stringify(canned.body));
      });
    });
    await new Promise<void>((resolve) => converter.listen(0, "127.0.0.1", resolve));
    const address = converter.address();
    if (typeof address === "string" || !address) throw new Error("no converter port");
    converterUrl = `http://127.0.0.1:${address.port}`;

    config = loadConfig({
      DATABASE_URL: DATABASE_URL!,
      ENVELOPE_MASTER_KEY: "07".repeat(32),
      SERVICE_TOKEN: SERVICE,
      ACTOR_TOKENS: `${ACTOR}:eran@hellochapter.com`,
      PORT: "0",
      SCAN_CONVERTER_URL: converterUrl,
    });
    gw = await buildGateway(config, { logger: false });
    await gw.app.ready();
  });

  afterAll(async () => {
    await gw.app.close();
    await gw.pool.end();
    await new Promise((resolve) => converter.close(resolve));
  });

  beforeEach(async () => {
    cannedQueue.length = 0;
    await gw.pool.query(
      "TRUNCATE finish_selections, render_jobs, layout_snapshots, briefs, reviews, id_map, event_log, envelopes, workstations, projects",
    );
  });

  const inject = (opts: InjectOptions) => gw.app.inject(opts);
  const svc = { authorization: `Bearer ${SERVICE}` };
  const actor = { authorization: `Bearer ${ACTOR}` };

  async function createProject(): Promise<string> {
    const res = await inject({
      method: "POST", url: "/projects", headers: svc, payload: { name: "scan-flow" },
    });
    return res.json().id as string;
  }

  async function uploadBundle(projectId: string, confirmationRequired = false) {
    cannedQueue.push({
      status: 200,
      body: { review_payload: reviewPayload(confirmationRequired) },
    });
    return inject({
      method: "POST",
      url: `/projects/${projectId}/scan-bundles`,
      headers: svc,
      payload: { dxf_base64: Buffer.from("stub").toString("base64") },
    });
  }

  it("upload creates a pending scan_commit0 review with the payload as content", async () => {
    const projectId = await createProject();
    const res = await uploadBundle(projectId);
    expect(res.statusCode).toBe(201);
    const { review_id, status, counts, content_hash } = res.json();
    expect(status).toBe("pending");
    expect(counts).toEqual({ walls: 17, doors: 5, windows: 3 });
    expect(content_hash).toMatch(/^[0-9a-f]{64}$/);

    const reviews = (await inject({
      method: "GET", url: `/projects/${projectId}/reviews`, headers: svc,
    })).json().reviews as { id: string; kind: string }[];
    expect(reviews.find((r) => r.id === review_id)?.kind).toBe("scan_commit0");
  });

  it("converter 422s pass through verbatim", async () => {
    const projectId = await createProject();
    cannedQueue.push({
      status: 422,
      body: { error: "multi_level_unsupported", message: "two elevations found" },
    });
    const res = await inject({
      method: "POST",
      url: `/projects/${projectId}/scan-bundles`,
      headers: svc,
      payload: { dxf_base64: Buffer.from("stub").toString("base64") },
    });
    expect(res.statusCode).toBe(422);
    expect(res.json()).toEqual({
      error: "multi_level_unsupported",
      message: "two elevations found",
    });
  });

  it("approve without ceiling confirmation is refused (422)", async () => {
    const projectId = await createProject();
    const reviewId = (await uploadBundle(projectId)).json().review_id as string;
    const res = await inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor, payload: {},
    });
    expect(res.statusCode).toBe(422);
    expect(res.json().error).toBe("confirmation_required");
  });

  it("heuristic unit requires a unit confirmation; mismatch is 422 unit_mismatch", async () => {
    const projectId = await createProject();
    const reviewId = (await uploadBundle(projectId, true)).json().review_id as string;

    const noUnit = await inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor,
      payload: { confirmations: { ceiling_height_mm: 2700 } },
    });
    expect(noUnit.statusCode).toBe(422);
    expect(noUnit.json().error).toBe("confirmation_required");

    const wrongUnit = await inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor,
      payload: { confirmations: { unit: "inch", ceiling_height_mm: 2700 } },
    });
    expect(wrongUnit.statusCode).toBe(422);
    expect(wrongUnit.json().error).toBe("unit_mismatch");

    const ok = await inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor,
      payload: { confirmations: { unit: "mm", ceiling_height_mm: 2700 } },
    });
    expect(ok.statusCode).toBe(200);
    expect(ok.json().status).toBe("approved");
  });

  it("rejecting needs no confirmations; re-upload supersedes the old review", async () => {
    const projectId = await createProject();
    const first = (await uploadBundle(projectId)).json().review_id as string;
    const rejected = await inject({
      method: "POST", url: `/reviews/${first}/reject`, headers: actor, payload: {},
    });
    expect(rejected.statusCode).toBe(200);

    const second = (await uploadBundle(projectId)).json().review_id as string;
    expect(second).not.toBe(first);
    // issue-commit0 must look at the LATEST review (the new pending one)
    const res = await inject({
      method: "POST", url: `/projects/${projectId}/issue-commit0`, headers: svc,
    });
    expect(res.statusCode).toBe(409);
    expect(res.json().error).toBe("scan_review_not_approved");
  });

  it("issue-commit0 preconditions: no review; not approved; no executor", async () => {
    const projectId = await createProject();
    const none = await inject({
      method: "POST", url: `/projects/${projectId}/issue-commit0`, headers: svc,
    });
    expect(none.json()).toEqual({ error: "no_scan_review" });

    const reviewId = (await uploadBundle(projectId)).json().review_id as string;
    await inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor,
      payload: { confirmations: { ceiling_height_mm: 2600 } },
    });
    // approved, but no executor connected -> the shared issuing path 409s
    const noExec = await inject({
      method: "POST", url: `/projects/${projectId}/issue-commit0`, headers: svc,
    });
    expect(noExec.statusCode).toBe(409);
    expect(noExec.json().error).toBe("no_executor_connected");

    const review = await gw.repos.getReview(reviewId);
    expect(review?.decision_payload).toEqual({
      confirmations: { ceiling_height_mm: 2600 },
    });
  });

  it("scan-bundles without a converter configured is 503", async () => {
    const bare = await buildGateway(
      loadConfig({
        DATABASE_URL: DATABASE_URL!,
        ENVELOPE_MASTER_KEY: "07".repeat(32),
        SERVICE_TOKEN: SERVICE,
        ACTOR_TOKENS: `${ACTOR}:eran@hellochapter.com`,
        PORT: "0",
      }),
      { logger: false },
    );
    try {
      const projectId = (await bare.app.inject({
        method: "POST", url: "/projects", headers: svc, payload: { name: "no-conv" },
      })).json().id as string;
      const res = await bare.app.inject({
        method: "POST",
        url: `/projects/${projectId}/scan-bundles`,
        headers: svc,
        payload: { dxf_base64: "c3R1Yg==" },
      });
      expect(res.statusCode).toBe(503);
      expect(res.json().error).toBe("scan_converter_unavailable");
    } finally {
      await bare.app.close();
      await bare.pool.end();
    }
  });

  it("UI review page renders confirmation inputs for pending scan reviews", async () => {
    const projectId = await createProject();
    await uploadBundle(projectId, true);
    const res = await inject({
      method: "GET",
      url: `/ui/projects/${projectId}/reviews?actor_token=${ACTOR}`,
    });
    expect(res.statusCode).toBe(200);
    expect(res.body).toContain('name="ceiling_height_mm"');
    expect(res.body).toContain('name="unit"');
  });

  it("UI form approve carries confirmations through the same validation", async () => {
    const projectId = await createProject();
    const reviewId = (await uploadBundle(projectId)).json().review_id as string;
    const bad = await inject({
      method: "POST",
      url: `/ui/reviews/${reviewId}/approve?actor_token=${ACTOR}`,
      headers: { "content-type": "application/x-www-form-urlencoded" },
      payload: "ceiling_height_mm=9999",
    });
    expect(bad.statusCode).toBe(422);

    const ok = await inject({
      method: "POST",
      url: `/ui/reviews/${reviewId}/approve?actor_token=${ACTOR}`,
      headers: { "content-type": "application/x-www-form-urlencoded" },
      payload: "ceiling_height_mm=2700",
    });
    expect(ok.statusCode).toBe(302);
    const review = await gw.repos.getReview(reviewId);
    expect(review?.status).toBe("approved");
    expect(review?.decision_payload).toEqual({ confirmations: { ceiling_height_mm: 2700 } });
  });

  // ---- Phase 5 (Q7): structural wall-flag confirmations on the scan card ----

  it("wall_flags persist and flow into BOTH the frozen snapshot and the commit ops", async () => {
    const { randomUUID } = await import("node:crypto");
    const { commit0LayoutFromReview } = await import("../src/layout/snapshot.js");
    const { opsFromScanLayout } = await import("../src/scan/ops.js");

    const projectId = await createProject();
    const reviewId = (await uploadBundle(projectId)).json().review_id as string;
    const approve = await inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor,
      payload: {
        confirmations: {
          ceiling_height_mm: 2700,
          wall_flags: {
            "W-001": { is_demising: true },
            "W-002": { is_exterior: true, is_load_bearing: true },
          },
        },
      },
    });
    expect(approve.statusCode).toBe(200);

    const review = await gw.repos.getReview(reviewId);
    const confirmations = (review?.decision_payload as { confirmations: { wall_flags: unknown } })
      .confirmations;
    expect(confirmations.wall_flags).toEqual({
      "W-001": { is_demising: true },
      "W-002": { is_exterior: true, is_load_bearing: true },
    });

    // the single shared derivation: flags land on the layout the ops AND the
    // snapshot are built from
    const { layout } = commit0LayoutFromReview(review!);
    const w1 = layout.walls.find((w) => w.id === "W-001")!;
    const w2 = layout.walls.find((w) => w.id === "W-002")!;
    expect(w1.is_demising).toBe(true);
    expect(w2.is_exterior).toBe(true);
    expect(w2.is_load_bearing).toBe(true);
    const ops = opsFromScanLayout(layout, { ceilingMm: 2700 });
    const createW1 = ops.find(
      (o) => o.op === "create_wall" && (o.args as { id: string }).id === "W-001",
    )!;
    expect((createW1.args as { flags: unknown }).flags).toMatchObject({ is_demising: true });

    // ...and the frozen commit0 snapshot carries them (simulated commit_result)
    await inject({
      method: "POST", url: `/projects/${projectId}/workstations`, headers: svc,
      payload: { workstation_id: "ws-design-01" },
    });
    const envelopeId = randomUUID();
    await gw.repos.insertIssuedEnvelope({
      envelopeId, projectId, workstationId: "ws-design-01", seq: 1,
      payload: JSON.stringify({ ttl_s: 600 }), sig: "0".repeat(128),
      commitLabel: "Commit #0",
      approvalRef: { review_id: reviewId, content_hash: review!.content_hash },
      issuedAt: new Date().toISOString(),
    });
    await gw.repos.recordCommitResult({ envelopeId, committed: true, idMapDelta: [], errors: [] });
    const snapshot = await gw.repos.getSnapshot(projectId, "commit0");
    const frozen = (snapshot!.layout as { walls: { id: string; is_demising?: boolean }[] }).walls;
    expect(frozen.find((w) => w.id === "W-001")?.is_demising).toBe(true);
  });

  it("wall_flags naming an unknown wall are refused (422)", async () => {
    const projectId = await createProject();
    const reviewId = (await uploadBundle(projectId)).json().review_id as string;
    const res = await inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor,
      payload: {
        confirmations: {
          ceiling_height_mm: 2700,
          wall_flags: { "W-099": { is_demising: true } },
        },
      },
    });
    expect(res.statusCode).toBe(422);
    expect(res.json().error).toBe("unknown_wall_flag");
  });

  it("UI renders flag checkboxes and the form parse round-trips them", async () => {
    const projectId = await createProject();
    const reviewId = (await uploadBundle(projectId)).json().review_id as string;
    const page = await inject({
      method: "GET",
      url: `/ui/projects/${projectId}/reviews?actor_token=${ACTOR}`,
    });
    expect(page.body).toContain('name="wall_flag.W-001.is_demising"');

    const ok = await inject({
      method: "POST",
      url: `/ui/reviews/${reviewId}/approve?actor_token=${ACTOR}`,
      headers: { "content-type": "application/x-www-form-urlencoded" },
      payload: "ceiling_height_mm=2700&wall_flag.W-001.is_demising=on&wall_flag.W-099.is_demising=ignored",
    });
    expect(ok.statusCode).toBe(302);
    const review = await gw.repos.getReview(reviewId);
    expect(review?.decision_payload).toEqual({
      confirmations: {
        ceiling_height_mm: 2700,
        wall_flags: { "W-001": { is_demising: true } },
      },
    });
  });
});
