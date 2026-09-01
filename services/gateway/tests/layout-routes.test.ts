// DB-backed Phase 4 layout flow: frozen commit0 snapshot -> compile-layout ->
// layout_commit1 review -> issue-commit1 preconditions -> commit1 snapshot
// frozen on commit_result. The compiler is a local stub HTTP server speaking
// the real /compile contract (request-recording, like the brief stub); commits
// are simulated through repos.recordCommitResult. Requires DATABASE_URL.
import { createServer, type Server } from "node:http";
import { randomUUID } from "node:crypto";
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
) as { meta: Record<string, unknown>; walls: unknown[] };

function scanReviewPayload(): Record<string, unknown> {
  return {
    layout: GOLDEN_LAYOUT,
    unit: {
      detected: "mm", insunits: 4, source: "insunits", confirmation_required: false,
      bbox_span_raw: 11400, bbox_span_mm: 11400,
    },
    height_assumption_mm: 2700,
    assumptions: [],
    flags: [],
    low_confidence: [],
    room_labels: [],
    counts: { walls: 17, doors: 5, windows: 3 },
  };
}

function compileResult(): Record<string, unknown> {
  return {
    layout: {
      ...GOLDEN_LAYOUT,
      meta: { ...GOLDEN_LAYOUT.meta, phase: "new", brief_version: 1 },
    },
    ops: [{ op: "set_phase_demolished", args: { target_id: "W-007" } }],
    demolition: [{ kind: "wall", id: "W-007" }],
    svgs: { existing: "<svg>existing</svg>", new: "<svg>new</svg>" },
    diagnostics: { attempts: 1, repair_retried: false },
  };
}

// one stub speaks both service contracts, routed by path; /compile is scripted
type Canned = { status: number; body: unknown };
const compileQueue: Canned[] = [];
const compileRequests: Record<string, unknown>[] = [];
let services: Server;
let servicesUrl: string;

describe.skipIf(!DATABASE_URL)("gateway layout flow (DB-backed)", () => {
  let gw: Gateway;
  let config: Config;

  beforeAll(async () => {
    services = createServer((req, res) => {
      let raw = "";
      req.on("data", (c) => (raw += c));
      req.on("end", () => {
        let canned: Canned;
        if (req.url === "/compile") {
          compileRequests.push(JSON.parse(raw) as Record<string, unknown>);
          canned = compileQueue.shift() ?? { status: 200, body: compileResult() };
        } else {
          canned = { status: 200, body: { review_payload: scanReviewPayload() } };
        }
        res.writeHead(canned.status, { "content-type": "application/json" });
        res.end(JSON.stringify(canned.body));
      });
    });
    await new Promise<void>((resolve) => services.listen(0, "127.0.0.1", resolve));
    const address = services.address();
    if (typeof address === "string" || !address) throw new Error("no stub port");
    servicesUrl = `http://127.0.0.1:${address.port}`;

    config = loadConfig({
      DATABASE_URL: DATABASE_URL!,
      ENVELOPE_MASTER_KEY: "07".repeat(32),
      SERVICE_TOKEN: SERVICE,
      ACTOR_TOKENS: `${ACTOR}:eran@hellochapter.com`,
      PORT: "0",
      SCAN_CONVERTER_URL: servicesUrl,
      LAYOUT_COMPILER_URL: servicesUrl,
    });
    gw = await buildGateway(config, { logger: false });
    await gw.app.ready();
  });

  afterAll(async () => {
    await gw.app.close();
    await gw.pool.end();
    await new Promise((resolve) => services.close(resolve));
  });

  beforeEach(async () => {
    compileQueue.length = 0;
    compileRequests.length = 0;
    await gw.pool.query(
      "TRUNCATE layout_snapshots, briefs, reviews, id_map, event_log, envelopes, workstations, projects",
    );
  });

  const inject = (opts: InjectOptions) => gw.app.inject(opts);
  const svc = { authorization: `Bearer ${SERVICE}` };
  const actor = { authorization: `Bearer ${ACTOR}` };

  async function createProject(): Promise<string> {
    const res = await inject({
      method: "POST", url: "/projects", headers: svc, payload: { name: "layout-flow" },
    });
    return res.json().id as string;
  }

  /** Real scan review + approval, then a simulated committed Commit #0 envelope:
   *  recordCommitResult freezes the commit0 snapshot exactly like production. */
  async function commit0(projectId: string, ceilingMm = 2600): Promise<void> {
    const upload = await inject({
      method: "POST",
      url: `/projects/${projectId}/scan-bundles`,
      headers: svc,
      payload: { dxf_base64: Buffer.from("stub").toString("base64") },
    });
    const reviewId = upload.json().review_id as string;
    await inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor,
      payload: { confirmations: { ceiling_height_mm: ceilingMm } },
    });
    const review = await gw.repos.getReview(reviewId);
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
    await gw.repos.recordCommitResult({
      envelopeId, committed: true, idMapDelta: [], errors: [],
    });
  }

  async function confirmedBrief(projectId: string): Promise<void> {
    const { review } = await gw.repos.createBriefWithReview(
      projectId,
      {
        meta: { project_id: projectId, brief_version: 1, source_sessions: ["session1_3br"] },
        rooms_required: [{ program: "bedroom", count: 3, confidence: 1 }],
      },
      { contradiction_count: 0 },
      false,
    );
    await inject({
      method: "POST", url: `/reviews/${review.id}/approve`, headers: actor, payload: {},
    });
  }

  it("commit0 snapshot is frozen with the confirmed ceiling applied", async () => {
    const projectId = await createProject();
    await commit0(projectId, 2600);
    const snapshot = await gw.repos.getSnapshot(projectId, "commit0");
    expect(snapshot).not.toBeNull();
    const layout = snapshot!.layout as { walls: { height: number }[] };
    expect(layout.walls).toHaveLength(17);
    expect(new Set(layout.walls.map((w) => w.height))).toEqual(new Set([2600]));
  });

  it("compile-layout preconditions: 404, commit0_not_done, no_brief, brief_not_confirmed", async () => {
    const missing = await inject({
      method: "POST", url: `/projects/${randomUUID()}/compile-layout`, headers: svc,
    });
    expect(missing.statusCode).toBe(404);

    const projectId = await createProject();
    const noCommit0 = await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    });
    expect(noCommit0.statusCode).toBe(409);
    expect(noCommit0.json().error).toBe("commit0_not_done");

    await commit0(projectId);
    const noBrief = await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    });
    expect(noBrief.json().error).toBe("no_brief");

    await gw.repos.createBriefWithReview(
      projectId, { meta: { brief_version: 1 } }, {}, false,
    );
    const unconfirmed = await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    });
    expect(unconfirmed.statusCode).toBe(409);
    expect(unconfirmed.json().error).toBe("brief_not_confirmed");
    expect(compileRequests).toHaveLength(0); // no precondition failure reaches the compiler
  });

  it("compile-layout sends the FROZEN snapshot and creates a pending layout_commit1 review", async () => {
    const projectId = await createProject();
    await commit0(projectId, 2600);
    await confirmedBrief(projectId);

    const res = await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.status).toBe("pending");
    expect(body.counts.demolished).toBe(1);
    expect(body.content_hash).toMatch(/^[0-9a-f]{64}$/);

    // the compiler saw the frozen snapshot (ceiling applied), not the raw review layout
    expect(compileRequests).toHaveLength(1);
    const sent = compileRequests[0] as {
      brief: { meta: { confirmed_by_client?: boolean } };
      existing_layout: { walls: { height: number }[] };
    };
    expect(sent.brief.meta.confirmed_by_client).toBe(true);
    expect(new Set(sent.existing_layout.walls.map((w) => w.height))).toEqual(new Set([2600]));

    const review = await gw.repos.getReview(body.review_id as string);
    expect(review?.kind).toBe("layout_commit1");
    const content = review?.content as { ops: unknown[]; svgs: { new: string } };
    expect(content.ops).toEqual([{ op: "set_phase_demolished", args: { target_id: "W-007" } }]);
    expect(content.svgs.new).toBe("<svg>new</svg>");
  });

  it("compiler 422 -> gateway 422 + layout_failure review (never auto-approved)", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    compileQueue.push({
      status: 422,
      body: { error: "layout_invalid", message: "validator said no", raw_outputs: [{}] },
    });
    const res = await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    });
    expect(res.statusCode).toBe(422);
    expect(res.json().error).toBe("layout_invalid");
    const failure = await gw.repos.latestReviewOfKind(projectId, "layout_failure");
    expect(failure?.status).toBe("pending");
  });

  it("issue-commit1 preconditions and the verbatim-ops path to the envelope issuer", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);

    const noReview = await inject({
      method: "POST", url: `/projects/${projectId}/issue-commit1`, headers: svc,
    });
    expect(noReview.json().error).toBe("no_layout_review");

    const reviewId = (await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    })).json().review_id as string;

    const pending = await inject({
      method: "POST", url: `/projects/${projectId}/issue-commit1`, headers: svc,
    });
    expect(pending.statusCode).toBe(409);
    expect(pending.json().error).toBe("layout_review_not_approved");

    await inject({ method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor, payload: {} });
    // approved, but no executor connected -> the shared issuing path 409s
    const noExec = await inject({
      method: "POST", url: `/projects/${projectId}/issue-commit1`, headers: svc,
    });
    expect(noExec.statusCode).toBe(409);
    expect(noExec.json().error).toBe("no_executor_connected");
  });

  it("commit1 snapshot freezes on commit_result; repeat compile/issue are 409", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    const compile = (await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    })).json();
    const reviewId = compile.review_id as string;
    await inject({ method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor, payload: {} });

    const review = await gw.repos.getReview(reviewId);
    const envelopeId = randomUUID();
    await gw.repos.insertIssuedEnvelope({
      envelopeId, projectId, workstationId: "ws-design-01", seq: 2,
      payload: JSON.stringify({ ttl_s: 600 }), sig: "0".repeat(128),
      commitLabel: "Commit #1",
      approvalRef: { review_id: reviewId, content_hash: review!.content_hash },
      issuedAt: new Date().toISOString(),
    });
    await gw.repos.recordCommitResult({
      envelopeId, committed: true, idMapDelta: [], errors: [],
    });

    const snapshot = await gw.repos.getSnapshot(projectId, "commit1");
    expect(snapshot).not.toBeNull();
    expect(snapshot!.seq).toBe(2);
    const content = review?.content as { layout: { meta: { phase: string } } };
    expect((snapshot!.layout as { meta: { phase: string } }).meta.phase).toBe("new");
    expect(snapshot!.layout).toEqual(content.layout); // frozen verbatim

    const state = (await inject({
      method: "GET", url: `/projects/${projectId}/state`, headers: svc,
    })).json();
    expect(state.commit1_done).toBe(true);

    const again = await inject({
      method: "POST", url: `/projects/${projectId}/issue-commit1`, headers: svc,
    });
    expect(again.json().error).toBe("commit1_already_done");
    const recompile = await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    });
    expect(recompile.json().error).toBe("commit1_already_done");
  });

  it("compile-layout without a compiler configured is 503", async () => {
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
        method: "POST", url: "/projects", headers: svc, payload: { name: "no-compiler" },
      })).json().id as string;
      const res = await bare.app.inject({
        method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
      });
      expect(res.statusCode).toBe(503);
      expect(res.json().error).toBe("layout_compiler_unavailable");
    } finally {
      await bare.app.close();
      await bare.pool.end();
    }
  });

  it("UI review page renders the side-by-side card for layout_commit1", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    await inject({ method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc });
    const res = await inject({
      method: "GET",
      url: `/ui/projects/${projectId}/reviews?actor_token=${ACTOR}`,
    });
    expect(res.statusCode).toBe(200);
    expect(res.body).toContain("data:image/svg+xml;base64,");
    expect(res.body).toContain("Demolition by phasing (1)");
    expect(res.body).toContain("W-007");
  });
});
