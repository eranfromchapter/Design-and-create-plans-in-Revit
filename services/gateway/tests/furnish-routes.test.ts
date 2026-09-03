// DB-backed Phase 5 interior flow: full chain to a frozen commit1 snapshot,
// then furnish-layout -> interior_plan review (the branch delta Phase 6
// consumes; Phase 5 issues NO envelope). The compiler is a stub speaking the
// real /compile + /furnish contracts; commits are simulated through
// repos.recordCommitResult. Requires DATABASE_URL.
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
    assumptions: [], flags: [], low_confidence: [], room_labels: [],
    counts: { walls: 17, doors: 5, windows: 3 },
  };
}

const NEW_LAYOUT = {
  ...GOLDEN_LAYOUT,
  meta: { ...GOLDEN_LAYOUT.meta, phase: "new", brief_version: 1 },
};

function compileResult(): Record<string, unknown> {
  return {
    layout: NEW_LAYOUT,
    ops: [{ op: "set_phase_demolished", args: { target_id: "W-007" } }],
    demolition: [{ kind: "wall", id: "W-007" }],
    svgs: { existing: "<svg>existing</svg>", new: "<svg>new</svg>" },
    diagnostics: { attempts: 1, repair_retried: false },
  };
}

const PLACED_ITEM = {
  id: "F-001",
  kind: "table",
  revit_family: "CHPT_Nightstand_PLACEHOLDER",
  revit_type: "Nightstand_450x450_PLACEHOLDER",
  center: [3500.0, 271.0],
  rotation_deg: 0,
  footprint: [450, 450],
  clearance_front: 0,
  wall_seeking: true,
};

function furnishResult(): Record<string, unknown> {
  return {
    layout: {
      ...NEW_LAYOUT,
      furniture: [{ room_id: "R-001", items: [PLACED_ITEM] }],
    },
    ops: [
      {
        op: "place_family",
        args: {
          id: "F-001",
          revit_family: "CHPT_Nightstand_PLACEHOLDER",
          revit_type: "Nightstand_450x450_PLACEHOLDER",
          center: [3500.0, 271.0],
          rotation_deg: 0,
          footprint: [450, 450],
          level: "Level 1",
        },
      },
    ],
    svgs: { commit1: "<svg>commit1</svg>", furnished: "<svg>furnished</svg>" },
    unplaced: [
      { item: { id: "F-013", kind: "lav" }, room_id: "R-007", reason: "no legal position" },
    ],
    diagnostics: {
      attempts: 1, repair_retried: false, elapsed_ms: 42.5,
      items: [], total_candidates: 7, spiral_total: 0, walls_tried: 1,
    },
  };
}

type Canned = { status: number; body: unknown };
const furnishQueue: Canned[] = [];
const furnishRequests: Record<string, unknown>[] = [];
let services: Server;
let servicesUrl: string;

describe.skipIf(!DATABASE_URL)("gateway interior flow (DB-backed)", () => {
  let gw: Gateway;
  let config: Config;

  beforeAll(async () => {
    services = createServer((req, res) => {
      let raw = "";
      req.on("data", (c) => (raw += c));
      req.on("end", () => {
        let canned: Canned;
        if (req.url === "/furnish") {
          furnishRequests.push(JSON.parse(raw) as Record<string, unknown>);
          canned = furnishQueue.shift() ?? { status: 200, body: furnishResult() };
        } else if (req.url === "/compile") {
          canned = { status: 200, body: compileResult() };
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
    furnishQueue.length = 0;
    furnishRequests.length = 0;
    await gw.pool.query(
      "TRUNCATE finish_selections, render_jobs, layout_snapshots, briefs, reviews, id_map, event_log, envelopes, workstations, projects",
    );
  });

  const inject = (opts: InjectOptions) => gw.app.inject(opts);
  const svc = { authorization: `Bearer ${SERVICE}` };
  const actor = { authorization: `Bearer ${ACTOR}` };

  async function createProject(): Promise<string> {
    const res = await inject({
      method: "POST", url: "/projects", headers: svc, payload: { name: "interior-flow" },
    });
    return res.json().id as string;
  }

  async function simulateCommit(projectId: string, reviewId: string, seq: number, label: string) {
    const review = await gw.repos.getReview(reviewId);
    const envelopeId = randomUUID();
    await gw.repos.insertIssuedEnvelope({
      envelopeId, projectId, workstationId: "ws-design-01", seq,
      payload: JSON.stringify({ ttl_s: 600 }), sig: "0".repeat(128),
      commitLabel: label,
      approvalRef: { review_id: reviewId, content_hash: review!.content_hash },
      issuedAt: new Date().toISOString(),
    });
    await gw.repos.recordCommitResult({ envelopeId, committed: true, idMapDelta: [], errors: [] });
  }

  async function commit0(projectId: string): Promise<void> {
    const upload = await inject({
      method: "POST",
      url: `/projects/${projectId}/scan-bundles`,
      headers: svc,
      payload: { dxf_base64: Buffer.from("stub").toString("base64") },
    });
    const reviewId = upload.json().review_id as string;
    await inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor,
      payload: { confirmations: { ceiling_height_mm: 2700 } },
    });
    await inject({
      method: "POST", url: `/projects/${projectId}/workstations`, headers: svc,
      payload: { workstation_id: "ws-design-01" },
    });
    await simulateCommit(projectId, reviewId, 1, "Commit #0");
  }

  async function confirmedBrief(projectId: string): Promise<void> {
    const { review } = await gw.repos.createBriefWithReview(
      projectId,
      { meta: { project_id: projectId, brief_version: 1, source_sessions: ["session1_3br"] } },
      {},
      false,
    );
    await inject({ method: "POST", url: `/reviews/${review.id}/approve`, headers: actor, payload: {} });
  }

  async function commit1(projectId: string): Promise<void> {
    const reviewId = (await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    })).json().review_id as string;
    await inject({ method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor, payload: {} });
    await simulateCommit(projectId, reviewId, 2, "Commit #1");
  }

  const furnish = (projectId: string) =>
    inject({ method: "POST", url: `/projects/${projectId}/furnish-layout`, headers: svc });

  it("precondition ladder: 404, commit0_not_done, commit1_not_done, brief_not_confirmed", async () => {
    expect((await furnish(randomUUID())).statusCode).toBe(404);

    const projectId = await createProject();
    expect((await furnish(projectId)).json().error).toBe("commit0_not_done");

    await commit0(projectId);
    expect((await furnish(projectId)).json().error).toBe("commit1_not_done");

    await gw.repos.createBriefWithReview(
      projectId, { meta: { brief_version: 1 } }, {}, false,
    );
    const compileReview = (await inject({
      method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc,
    }));
    expect(compileReview.statusCode).toBe(409); // unconfirmed brief blocks compile too
    expect(furnishRequests).toHaveLength(0);
  });

  it("a newer unconfirmed brief blocks furnish: 409, compiler never called", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    await commit1(projectId);
    // brief v2 arrives after Commit #1 but the client never confirms it — the
    // interior agent must not furnish against a superseded brief
    await gw.repos.createBriefWithReview(projectId, { meta: { note: "v2 draft" } }, {}, false);
    const res = await furnish(projectId);
    expect(res.statusCode).toBe(409);
    expect(res.json().error).toBe("brief_not_confirmed");
    expect(furnishRequests).toHaveLength(0);
  });

  it("furnish creates a pending interior_plan review carrying the branch delta", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    await commit1(projectId);

    const res = await furnish(projectId);
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.status).toBe("pending");
    expect(body.counts).toEqual({ items_placed: 1, items_unplaced: 1, rooms_furnished: 1 });
    expect(body.content_hash).toMatch(/^[0-9a-f]{64}$/);

    // the compiler saw the frozen snapshots + the exact committed Commit #1 ops
    expect(furnishRequests).toHaveLength(1);
    const sent = furnishRequests[0] as {
      brief: { meta: { confirmed_by_client?: boolean } };
      commit1_layout: { meta: { phase: string } };
      commit1_ops: unknown[];
    };
    expect(sent.brief.meta.confirmed_by_client).toBe(true);
    expect(sent.commit1_layout.meta.phase).toBe("new");
    expect(sent.commit1_ops).toEqual([{ op: "set_phase_demolished", args: { target_id: "W-007" } }]);

    const review = await gw.repos.getReview(body.review_id as string);
    expect(review?.kind).toBe("interior_plan");
    const content = review?.content as {
      ops: { op: string }[];
      svgs: { furnished: string };
      unplaced: { item: { id: string } }[];
    };
    expect(content.ops.map((o) => o.op)).toEqual(["place_family"]);
    expect(content.svgs.furnished).toBe("<svg>furnished</svg>");
    expect(content.unplaced.map((u) => u.item.id)).toEqual(["F-013"]);

    // Phase 5 issues NO envelope: the last committed seq is still Commit #1's
    expect(await gw.repos.lastCommittedSeq(projectId)).toBe(2);
  });

  it("furnish failure -> 422 + interior_failure review, never auto-approved", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    await commit1(projectId);
    furnishQueue.push({
      status: 422,
      body: { error: "proposal_invalid", message: "3 strikes", raw_outputs: [{}] },
    });
    const res = await furnish(projectId);
    expect(res.statusCode).toBe(422);
    expect(res.json().error).toBe("proposal_invalid");
    const failure = await gw.repos.latestReviewOfKind(projectId, "interior_failure");
    expect(failure?.status).toBe("pending");
  });

  it("re-runs supersede; interior_plan_ready flips only on approval of the LATEST", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    await commit1(projectId);

    const first = (await furnish(projectId)).json().review_id as string;
    const state1 = (await inject({
      method: "GET", url: `/projects/${projectId}/state`, headers: svc,
    })).json();
    expect(state1.interior_plan_ready).toBe(false);

    await inject({ method: "POST", url: `/reviews/${first}/approve`, headers: actor, payload: {} });
    const state2 = (await inject({
      method: "GET", url: `/projects/${projectId}/state`, headers: svc,
    })).json();
    expect(state2.interior_plan_ready).toBe(true);

    // a re-run supersedes the approved plan: latest is pending again
    const second = (await furnish(projectId)).json().review_id as string;
    expect(second).not.toBe(first);
    const state3 = (await inject({
      method: "GET", url: `/projects/${projectId}/state`, headers: svc,
    })).json();
    expect(state3.interior_plan_ready).toBe(false);
  });

  it("a newer CONFIRMED brief supersedes an approved plan (staleness gate)", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    await commit1(projectId);
    const reviewId = (await furnish(projectId)).json().review_id as string;
    await inject({ method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor, payload: {} });
    const ready = (await inject({
      method: "GET", url: `/projects/${projectId}/state`, headers: svc,
    })).json();
    expect(ready.interior_plan_ready).toBe(true);

    // brief v2 confirmed AFTER the plan was approved: the plan was built from
    // v1, so Phase 6's merge gate must see it as stale (handoff contract)
    await confirmedBrief(projectId);
    const stale = (await inject({
      method: "GET", url: `/projects/${projectId}/state`, headers: svc,
    })).json();
    expect(stale.interior_plan_ready).toBe(false);
  });

  it("UI review page renders the interior card with the unplaced table", async () => {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    await commit1(projectId);
    await furnish(projectId);
    const res = await inject({
      method: "GET",
      url: `/ui/projects/${projectId}/reviews?actor_token=${ACTOR}`,
    });
    expect(res.statusCode).toBe(200);
    expect(res.body).toContain("Furnished proposal");
    expect(res.body).toContain("Unplaced — needs review (1)");
    expect(res.body).toContain("F-013");
  });

  it("furnish-layout without a compiler configured is 503", async () => {
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
        method: "POST", url: `/projects/${projectId}/furnish-layout`, headers: svc,
      });
      expect(res.statusCode).toBe(503);
      expect(res.json().error).toBe("layout_compiler_unavailable");
    } finally {
      await bare.app.close();
      await bare.pool.end();
    }
  });
});
