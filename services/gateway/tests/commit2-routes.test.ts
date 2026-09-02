// DB-backed Phase 6 flow: plan-mep -> mep_plan (the MEP branch delta), merge-commit2
// -> commit2_merge under the shared ≤3-round budget derived from the merge chain,
// issue-commit2 under a fresh seq, the commit2 snapshot, clash_delta merging, the
// MergeResult verifier and the /envelopes approval guard. The compiler is a stub
// speaking the real /plan-mep + /merge contracts (the merge stub REPLAYS prior
// actions and shifts E-001 per injected pair, like the real gate); executor frames
// arrive through repos or a real WSS executor. Requires DATABASE_URL.
import { createServer, type Server } from "node:http";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import type { InjectOptions } from "fastify";
import { WebSocket } from "ws";
import { idMapHash } from "@chapter/contracts";
import { loadConfig, type Config } from "../src/config.js";
import { buildGateway, type Gateway } from "../src/app.js";
import { mergeClashPairs } from "../src/db/repos.js";
import { clashPairsFromErrors, isHardRollback, verifyMergeResult } from "../src/layout/merge-verify.js";
import { mergeResultSchema } from "../src/layout/merge-client.js";

const DATABASE_URL = process.env["DATABASE_URL"];
const SERVICE = "service-token-0123456789";
const ACTOR = "actor-token-eran";

const GOLDEN_LAYOUT = JSON.parse(
  readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "fixtures", "layouts", "2br_golden.json"),
    "utf8",
  ),
) as { meta: Record<string, unknown>; walls: { id: string; start: [number, number]; end: [number, number] }[] };

function scanReviewPayload(): Record<string, unknown> {
  return {
    layout: GOLDEN_LAYOUT,
    unit: { detected: "mm", insunits: 4, source: "insunits", confirmation_required: false,
      bbox_span_raw: 11400, bbox_span_mm: 11400 },
    height_assumption_mm: 2700,
    assumptions: [], flags: [], low_confidence: [], room_labels: [],
    counts: { walls: 17, doors: 5, windows: 3 },
  };
}

const NEW_LAYOUT = { ...GOLDEN_LAYOUT, meta: { ...GOLDEN_LAYOUT.meta, phase: "new", brief_version: 1 } };

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
  id: "F-001", kind: "table",
  revit_family: "CHPT_Nightstand_PLACEHOLDER", revit_type: "Nightstand_450x450_PLACEHOLDER",
  center: [3500.0, 271.0], rotation_deg: 0, footprint: [450, 450], clearance_front: 0, wall_seeking: true,
};
const FURNISHED_LAYOUT = { ...NEW_LAYOUT, furniture: [{ room_id: "R-001", items: [PLACED_ITEM] }] };
const INTERIOR_OPS = [
  {
    op: "place_family",
    args: {
      id: "F-001", revit_family: "CHPT_Nightstand_PLACEHOLDER", revit_type: "Nightstand_450x450_PLACEHOLDER",
      center: [3500.0, 271.0], rotation_deg: 0, footprint: [450, 450], level: "Level 1",
    },
  },
];

function furnishResult(): Record<string, unknown> {
  return {
    layout: FURNISHED_LAYOUT,
    ops: INTERIOR_OPS,
    svgs: { commit1: "<svg>commit1</svg>", furnished: "<svg>furnished</svg>" },
    unplaced: [],
    diagnostics: {
      attempts: 1, repair_retried: false, elapsed_ms: 42.5,
      items: [{ item_id: "F-001", wall_id: "W-001", placed: true }], total_candidates: 7, spiral_total: 0, walls_tried: 1,
    },
  };
}

type Op = { op: string; args: Record<string, unknown> };
const MEP_OPS: Op[] = [
  { op: "create_pipe", args: { id: "P-001", system: "sanitary", pipe_type: "CHPT_Pipe_PVC_DWV_PLACEHOLDER",
    level: "Level 1", path: [[0, 1000, -300], [0, 1000, 2700]], diameter: 76 } },
  { op: "place_device", args: { id: "E-001", kind: "receptacle", host_wall_id: "W-001", offset: 1912.5,
    height_afl: 380, face: "right" } },
  { op: "create_conduit", args: { id: "Q-001", level: "Level 1", path: [[0, 1912.5, 380], [0, 1912.5, 2600]], diameter: 21 } },
];
const CHECK: Op = { op: "run_interference_check", args: { scope: "last_commit" } };

function mepPlan(blocking: string[] = []): Record<string, unknown> {
  return {
    layout: FURNISHED_LAYOUT,
    inputs: { panel: blocking.length ? null : [50, 3000], levels_source: blocking.length ? "missing" : "confirmation" },
    stacks: [{ id: "P-001", wall_id: "W-001", offset: 1000, xy: [0, 1000], diameter: 76, fixtures: [], snapped: false }],
    branches: [], fixture_routes: [],
    devices: [{ id: "E-001", kind: "receptacle", rule: "E-1", room_id: "R-001", host_wall_id: "W-001", offset: 1912.5, height_afl: 380, face: "right" }],
    home_runs: [{ device_id: "E-001", conduit_id: "Q-001" }],
    ops: MEP_OPS,
    review_items: blocking.map((code) => ({ code, severity: "blocking", refs: [], message: `${code} needs the card` })),
    blocking,
    svgs: { furnished: "<svg>furnished</svg>", mep: "<svg>mep</svg>" },
    diagnostics: { elapsed_ms: 12.0, counters: {} },
    counts: { devices: 1, receptacle: 1, gfci: 0, switch: 0, receptacle_240: 0, pipes: 1, stacks: 1, conduits: 1,
      review_items: blocking.length, blocking: blocking.length, extensions: { appliance: 0 } },
  };
}

interface MergeReq {
  interior: { review_id: string; content_hash: string; ops: Op[]; layout: unknown };
  mep: { review_id: string; content_hash: string; plan: { ops: Op[] } };
  iterations_used: number;
  iteration: number;
  prior_actions: { action: string; params: { after?: { offset: number; face: string } } }[];
  clash_pairs: { a_id: string; b_id: string; kind: string }[];
}

/** The stub merge gate: replays prior shift_device actions, then shifts E-001 by 150
 *  away from P-001 per injected pair (Phase B) — the real gate's golden behaviour. */
function defaultMerge(req: MergeReq): Record<string, unknown> {
  const mepOps = structuredClone(req.mep.plan.ops);
  const device = mepOps.find((o) => o.args["id"] === "E-001")!;
  for (const a of req.prior_actions) {
    if (a.action === "shift_device" && a.params.after) {
      device.args["offset"] = a.params.after.offset;
      device.args["face"] = a.params.after.face;
    }
  }
  const actions: unknown[] = [];
  let used = req.iterations_used;
  if (req.clash_pairs.length) {
    used += 1;
    const before = device.args["offset"] as number;
    device.args["offset"] = before - 150;
    actions.push({
      iteration: req.iteration, trigger: "phase_b", pair: req.clash_pairs[0], lower: "E-001", lower_priority: 4,
      higher: "P-001", higher_priority: 1, action: "shift_device",
      params: { before: { offset: before, face: "right" }, after: { offset: before - 150, face: "right" }, k: 1, away_from: "P-001" },
      changed: true,
    });
  }
  const ops = [...req.interior.ops, ...mepOps, CHECK];
  return {
    status: "clean", iteration: req.iteration, iterations_used: used,
    interior: { review_id: req.interior.review_id, content_hash: req.interior.content_hash, ops_count: req.interior.ops.length, ops_verbatim: true },
    mep: { review_id: req.mep.review_id, content_hash: req.mep.content_hash, ops_count: mepOps.length },
    layout: req.interior.layout, ops, actions, replan_deltas: [], dropped: [],
    clash_report: {
      budget: { limit: 3, used, remaining: 3 - used },
      phase_a: { rounds: [] },
      phase_b: { replans: req.clash_pairs.length ? [{ iteration: req.iteration, pairs: req.clash_pairs, actions }] : [] },
      prisms: { furniture: 1, pipe: 1, device: 1, conduit: 1 }, open_clashes: [], status: "clean",
    },
    svgs: { commit1: "<svg>commit1</svg>", merged: `<svg>merged-${req.iteration}</svg>` },
    blocked_reason: null,
    counts: { ops: ops.length, place_family: 1, create_pipe: 1, place_device: 1, create_conduit: 1, run_interference_check: 1 },
  };
}

type Canned = { status: number; body: unknown | ((req: MergeReq) => unknown) };
const mepQueue: Canned[] = [];
const mergeQueue: Canned[] = [];
const mepRequests: Record<string, unknown>[] = [];
const mergeRequests: MergeReq[] = [];
let services: Server;
let servicesUrl: string;

describe.skipIf(!DATABASE_URL)("gateway Phase 6 flow (DB-backed)", () => {
  let gw: Gateway;
  let config: Config;
  let port: number;

  beforeAll(async () => {
    services = createServer((req, res) => {
      let raw = "";
      req.on("data", (c) => (raw += c));
      req.on("end", () => {
        let canned: Canned;
        const parsed = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
        if (req.url === "/plan-mep") {
          mepRequests.push(parsed);
          canned = mepQueue.shift() ?? { status: 200, body: mepPlan(parsed["confirmations"] && Object.keys(parsed["confirmations"] as object).length ? [] : ["levels_missing", "panel_missing"]) };
        } else if (req.url === "/merge") {
          const mreq = parsed as unknown as MergeReq;
          mergeRequests.push(mreq);
          canned = mergeQueue.shift() ?? { status: 200, body: defaultMerge };
          if (typeof canned.body === "function") canned = { status: canned.status, body: (canned.body as (r: MergeReq) => unknown)(mreq) };
        } else if (req.url === "/furnish") {
          canned = { status: 200, body: furnishResult() };
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
    const baseUrl = await gw.app.listen({ port: 0, host: "127.0.0.1" });
    port = Number(new URL(baseUrl).port);
  });

  afterAll(async () => {
    await gw.app.close();
    await gw.pool.end();
    await new Promise((resolve) => services.close(resolve));
  });

  beforeEach(async () => {
    mepQueue.length = 0;
    mergeQueue.length = 0;
    mepRequests.length = 0;
    mergeRequests.length = 0;
    await gw.pool.query(
      "TRUNCATE layout_snapshots, briefs, reviews, id_map, event_log, envelopes, workstations, projects",
    );
  });

  const inject = (opts: InjectOptions) => gw.app.inject(opts);
  const svc = { authorization: `Bearer ${SERVICE}` };
  const actor = { authorization: `Bearer ${ACTOR}` };
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  async function createProject(): Promise<string> {
    const res = await inject({ method: "POST", url: "/projects", headers: svc, payload: { name: "phase6" } });
    return res.json().id as string;
  }

  async function approve(reviewId: string): Promise<void> {
    const res = await inject({ method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor, payload: {} });
    expect(res.statusCode).toBe(200);
  }

  async function issueFor(projectId: string, reviewId: string, seq: number, label: string): Promise<string> {
    const review = await gw.repos.getReview(reviewId);
    const envelopeId = randomUUID();
    await gw.repos.insertIssuedEnvelope({
      envelopeId, projectId, workstationId: "ws-design-01", seq,
      payload: JSON.stringify({ ttl_s: 600 }), sig: "0".repeat(128),
      commitLabel: label,
      approvalRef: { review_id: reviewId, content_hash: review!.content_hash },
      issuedAt: new Date().toISOString(),
    });
    return envelopeId;
  }

  const commitEnvelope = (envelopeId: string) =>
    gw.repos.recordCommitResult({ envelopeId, committed: true, idMapDelta: [], errors: [] });
  const rollbackEnvelope = (envelopeId: string, errors: unknown[]) =>
    gw.repos.recordCommitResult({ envelopeId, committed: false, idMapDelta: [], errors });
  const INTERFERENCE = [{ op_index: 4, code: "interference", message: "P-001~E-001" }];

  async function commit0(projectId: string): Promise<void> {
    const upload = await inject({
      method: "POST", url: `/projects/${projectId}/scan-bundles`, headers: svc,
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
    await commitEnvelope(await issueFor(projectId, reviewId, 1, "Commit #0"));
  }

  async function confirmedBrief(projectId: string): Promise<void> {
    const { review } = await gw.repos.createBriefWithReview(
      projectId, { meta: { project_id: projectId, brief_version: 1, source_sessions: ["session1_3br"] } }, {}, false,
    );
    await approve(review.id);
  }

  async function commit1(projectId: string): Promise<void> {
    const reviewId = (await inject({ method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc })).json().review_id as string;
    await approve(reviewId);
    await commitEnvelope(await issueFor(projectId, reviewId, 2, "Commit #1"));
  }

  async function approvedInterior(projectId: string): Promise<string> {
    const reviewId = (await inject({ method: "POST", url: `/projects/${projectId}/furnish-layout`, headers: svc })).json().review_id as string;
    await approve(reviewId);
    return reviewId;
  }

  /** Full chain to an approved interior plan (Phases 0–5 simulated through repos). */
  async function chainToInterior(): Promise<{ projectId: string; interiorId: string }> {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId);
    await commit1(projectId);
    const interiorId = await approvedInterior(projectId);
    return { projectId, interiorId };
  }

  const planMep = (projectId: string, body?: Record<string, unknown>) =>
    inject({ method: "POST", url: `/projects/${projectId}/plan-mep`, headers: svc, payload: body });
  const merge = (projectId: string) =>
    inject({ method: "POST", url: `/projects/${projectId}/merge-commit2`, headers: svc });
  const issue = (projectId: string) =>
    inject({ method: "POST", url: `/projects/${projectId}/issue-commit2`, headers: svc });
  const state = async (projectId: string) =>
    (await inject({ method: "GET", url: `/projects/${projectId}/state`, headers: svc })).json();
  const CONFIRMATIONS = { confirmations: { panel: [50, 3000], slab_to_slab_mm: 3000 } };

  /** Approved, non-blocking mep_plan on top of the interior chain. */
  async function approvedMep(projectId: string): Promise<string> {
    const res = await planMep(projectId, CONFIRMATIONS);
    expect(res.statusCode).toBe(201);
    const id = res.json().review_id as string;
    await approve(id);
    return id;
  }

  async function approvedMerge(projectId: string): Promise<{ reviewId: string; body: Record<string, unknown> }> {
    const res = await merge(projectId);
    expect(res.statusCode, res.body).toBe(201);
    const body = res.json();
    await approve(body.review_id as string);
    return { reviewId: body.review_id as string, body };
  }

  // ---- plan-mep -------------------------------------------------------------------

  it("plan-mep ladder: 404, commit0/commit1, interior_plan_not_ready reasons, stale brief", async () => {
    expect((await planMep(randomUUID())).statusCode).toBe(404);
    const projectId = await createProject();
    expect((await planMep(projectId)).json().error).toBe("commit0_not_done");
    await commit0(projectId);
    expect((await planMep(projectId)).json().error).toBe("commit1_not_done");
    await confirmedBrief(projectId);
    await commit1(projectId);
    expect((await planMep(projectId)).json()).toEqual({ error: "interior_plan_not_ready", reason: "none" });
    const interiorId = (await inject({ method: "POST", url: `/projects/${projectId}/furnish-layout`, headers: svc })).json().review_id as string;
    expect((await planMep(projectId)).json()).toEqual({ error: "interior_plan_not_ready", reason: "pending" });
    await inject({ method: "POST", url: `/reviews/${interiorId}/reject`, headers: actor, payload: {} });
    expect((await planMep(projectId)).json()).toEqual({ error: "interior_plan_not_ready", reason: "rejected" });
    await approvedInterior(projectId);
    expect((await planMep(projectId, CONFIRMATIONS)).statusCode).toBe(201);
    // a newer CONFIRMED brief supersedes the interior plan
    const { review } = await gw.repos.createBriefWithReview(projectId, { meta: { brief_version: 2 } }, {}, false);
    await approve(review.id);
    expect((await planMep(projectId)).json()).toEqual({ error: "interior_plan_not_ready", reason: "stale_brief" });
    expect(mepRequests).toHaveLength(1);
  });

  it("plan-mep without confirmations: blocking items, pending review, mep_plan_ready stays false, merge refused", async () => {
    const { projectId, interiorId } = await chainToInterior();
    const res = await planMep(projectId, {});
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.blocking).toEqual(["levels_missing", "panel_missing"]);
    expect(body.status).toBe("pending");
    const review = await gw.repos.getReview(body.review_id as string);
    const content = review!.content as Record<string, unknown>;
    expect(content["interior_review_id"]).toBe(interiorId);
    expect(content["confirmations"]).toEqual({});
    expect(content["brief_version"]).toBe(1);
    expect((await state(projectId)).mep_plan_ready).toBe(false);
    await approve(body.review_id as string);
    expect((await state(projectId)).mep_plan_ready).toBe(false); // blocking items open
    const refused = await merge(projectId);
    expect(refused.statusCode).toBe(409);
    expect(refused.json()).toEqual({ error: "mep_review_items_open", codes: ["levels_missing", "panel_missing"] });
    // the compiler saw the frozen snapshots, the interior ops, the placer host walls
    const sent = mepRequests[0] as { commit1_ops: unknown[]; interior_ops: unknown[]; placer_wall_ids: Record<string, string>; furnished_layout: { furniture: unknown[] } };
    expect(sent.commit1_ops).toEqual([{ op: "set_phase_demolished", args: { target_id: "W-007" } }]);
    expect(sent.interior_ops).toEqual(INTERIOR_OPS);
    expect(sent.placer_wall_ids).toEqual({ "F-001": "W-001" });
    expect(sent.furnished_layout.furniture).toHaveLength(1);
  });

  it("confirmations carry forward; panel off every wall is 422; failure is a pending mep_failure", async () => {
    const { projectId } = await chainToInterior();
    await approvedMep(projectId);
    expect((await state(projectId)).mep_plan_ready).toBe(true);
    const rerun = await planMep(projectId); // no body: latest confirmations apply
    expect(rerun.statusCode).toBe(201);
    expect((mepRequests[1] as { confirmations: unknown }).confirmations).toEqual({ panel: [50, 3000], slab_to_slab_mm: 3000 });
    expect(rerun.json().status).toBe("pending"); // a re-run supersedes: ready flips off
    expect((await state(projectId)).mep_plan_ready).toBe(false);

    const off = await planMep(projectId, { confirmations: { panel: [-5000, -5000] } });
    expect(off.statusCode).toBe(422);
    expect(off.json().error).toBe("panel_not_on_wall");
    expect(mepRequests).toHaveLength(2); // never reached the compiler

    mepQueue.push({ status: 422, body: { error: "mep_internal", message: "boom", raw_outputs: [] } });
    const failed = await planMep(projectId, CONFIRMATIONS);
    expect(failed.statusCode).toBe(422);
    expect(failed.json().error).toBe("mep_internal");
    const failure = await gw.repos.latestReviewOfKind(projectId, "mep_failure");
    expect(failure?.status).toBe("pending");
    const bad = await planMep(projectId, { confirmations: { slab_to_slab_mm: 100 } });
    expect(bad.statusCode).toBeGreaterThanOrEqual(400); // zod refuses before the compiler is called
    expect(mepRequests).toHaveLength(3);
  });

  it("the UI confirmations form re-plans and redirects to the reviews page", async () => {
    const { projectId } = await chainToInterior();
    const res = await inject({
      method: "POST",
      url: `/ui/projects/${projectId}/plan-mep?actor_token=${ACTOR}`,
      headers: { "content-type": "application/x-www-form-urlencoded" },
      payload: "panel_x=50&panel_y=3000&slab_to_slab_mm=3000",
    });
    expect(res.statusCode).toBe(302);
    expect(res.headers.location).toBe(`/ui/projects/${projectId}/reviews?actor_token=${ACTOR}`);
    const plan = await gw.repos.latestReviewOfKind(projectId, "mep_plan");
    expect((plan!.content as { confirmations: unknown }).confirmations).toEqual({ panel: [50, 3000], slab_to_slab_mm: 3000 });
    const page = await inject({ method: "GET", url: `/ui/projects/${projectId}/reviews?actor_token=${ACTOR}` });
    expect(page.body).toContain("MEP proposal");
    expect(page.body).toContain("Stacks (1)");
  });

  // ---- merge-commit2 --------------------------------------------------------------

  it("merge ladder: no_mep_plan, not approved, stale, pending merge, awaiting issue", async () => {
    const { projectId } = await chainToInterior();
    expect((await merge(projectId)).json().error).toBe("no_mep_plan");
    const mepId = (await planMep(projectId, CONFIRMATIONS)).json().review_id as string;
    expect((await merge(projectId)).json()).toEqual({ error: "mep_plan_not_approved", status: "pending" });
    await approve(mepId);
    // a newer approved interior plan makes the mep plan stale
    await approvedInterior(projectId);
    expect((await merge(projectId)).json().error).toBe("mep_plan_stale");
    await approvedMep(projectId);
    const first = await merge(projectId);
    expect(first.statusCode).toBe(201);
    expect(first.json().status).toBe("pending");
    expect((await merge(projectId)).json()).toEqual({ error: "merge_review_pending", review_id: first.json().review_id });
    await approve(first.json().review_id as string);
    expect((await merge(projectId)).json()).toEqual({ error: "merge_review_awaiting_issue", review_id: first.json().review_id });
    expect(mergeRequests).toHaveLength(1);
  });

  it("plan 1 merges clean: content = interior ops + MEP ops + one trailing check, chain state exposed", async () => {
    const { projectId, interiorId } = await chainToInterior();
    const mepId = await approvedMep(projectId);
    const res = await merge(projectId);
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.iteration).toBe(1);
    expect(body.iterations_used).toBe(0);
    expect(body.clash_summary).toEqual({
      budget: { limit: 3, used: 0, remaining: 3 }, actions: 0, dropped: 0, replan_deltas: 0, interior_verbatim: true,
    });
    const sent = mergeRequests[0]!;
    expect(sent.interior.review_id).toBe(interiorId);
    expect(sent.mep.review_id).toBe(mepId);
    expect(sent.iterations_used).toBe(0);
    expect(sent.iteration).toBe(1);
    expect(sent.prior_actions).toEqual([]);
    expect(sent.clash_pairs).toEqual([]);
    expect(Object.keys(sent.mep.plan)).not.toContain("interior_review_id"); // MepPlan verbatim
    const review = await gw.repos.getReview(body.review_id as string);
    const content = review!.content as { ops: Op[]; prior_actions: unknown[]; interior: { review_id: string } };
    expect(content.ops.map((o) => o.op)).toEqual(["place_family", "create_pipe", "place_device", "create_conduit", "run_interference_check"]);
    expect(content.prior_actions).toEqual([]);
    const s = await state(projectId);
    expect(s.commit2).toMatchObject({
      chain: { interior_review_id: interiorId, mep_review_id: mepId },
      iteration: 1, iterations_used: 0, budget_limit: 3, budget_remaining: 3,
      merge_review_id: body.review_id, merge_status: "pending", envelope_status: null,
      clash_pairs: null, exhausted: false, failed: false, merge_current: true,
    });
    expect(s.commit2_done).toBe(false);
    // issue needs approval first
    expect((await issue(projectId)).json()).toEqual({ error: "merge_review_not_approved", status: "pending" });
  });

  it("recovery: interference rollbacks shift E-001 per round, then the 4th exhausts the budget → REVIEW → fresh chain", async () => {
    const { projectId } = await chainToInterior();
    await approvedMep(projectId);
    let seq = 3;
    const offsets: number[] = [];
    let last = await approvedMerge(projectId);
    for (let round = 1; round <= 3; round++) {
      const envelopeId = await issueFor(projectId, last.reviewId, seq++, "Commit #2");
      await rollbackEnvelope(envelopeId, INTERFERENCE);
      const s = await state(projectId);
      expect(s.commit2.envelope_status).toBe("rolled_back");
      expect(s.commit2.clash_pairs).toEqual([{ a_id: "P-001", b_id: "E-001", kind: "hard_interference" }]);
      expect(s.commit2.last_errors).toEqual(INTERFERENCE);
      expect(s.commit2.budget_remaining).toBe(3 - (round - 1));
      // the consumed review cannot be re-issued
      expect((await issue(projectId)).json()).toEqual({ error: "merge_review_consumed", review_id: last.reviewId });
      last = await approvedMerge(projectId);
      expect(last.body.iteration).toBe(round + 1);
      expect(last.body.iterations_used).toBe(round);
      const sent = mergeRequests[mergeRequests.length - 1]!;
      expect(sent.iterations_used).toBe(round - 1);
      expect(sent.clash_pairs).toEqual([{ a_id: "P-001", b_id: "E-001", kind: "hard_interference" }]);
      expect(sent.prior_actions).toHaveLength(round - 1); // every earlier round's action replays
      const content = (await gw.repos.getReview(last.reviewId))!.content as { ops: Op[]; actions: { action: string }[] };
      expect(content.actions.map((a) => a.action)).toEqual(["shift_device"]);
      offsets.push(content.ops.find((o) => o.args["id"] === "E-001")!.args["offset"] as number);
    }
    expect(offsets).toEqual([1762.5, 1612.5, 1462.5]);
    // fourth rollback: the budget is spent → commit2_failure (never auto-approved) + REVIEW
    const envelopeId = await issueFor(projectId, last.reviewId, seq, "Commit #2");
    await rollbackEnvelope(envelopeId, INTERFERENCE);
    const exhausted = await merge(projectId);
    expect(exhausted.statusCode).toBe(409);
    expect(exhausted.json()).toEqual({ error: "merge_budget_exhausted", iterations_used: 3 });
    const failure = await gw.repos.latestReviewOfKind(projectId, "commit2_failure");
    expect(failure?.status).toBe("pending");
    expect((failure!.content as { reason: string }).reason).toBe("merge_budget_exhausted");
    const s = await state(projectId);
    expect(s.commit2.exhausted).toBe(true);
    expect(s.commit2.budget_remaining).toBe(0);
    expect(s.commit2_done).toBe(false);
    expect(s.last_committed_seq).toBe(2); // the snapshot stays at Commit #1
    expect(await gw.repos.hasSnapshot(projectId, "commit1")).toBe(true);
    // branches retained: the interior plan is still the approved one
    expect((await gw.repos.latestReviewOfKind(projectId, "interior_plan"))!.status).toBe("approved");
    // a new mep_plan starts a FRESH chain with a fresh budget; the old merge is stale for issue
    await approvedMep(projectId);
    expect((await issue(projectId)).json().error).toBe("merge_review_stale");
    const fresh = await merge(projectId);
    expect(fresh.statusCode).toBe(201);
    expect(fresh.json()).toMatchObject({ iteration: 1, iterations_used: 0 });
    expect(mergeRequests[mergeRequests.length - 1]!.prior_actions).toEqual([]);
    expect((await state(projectId)).commit2).toMatchObject({ exhausted: false, iterations_used: 0, merge_current: true });
  });

  it("hard executor codes fail the chain; transient codes are re-issuable with a cap", async () => {
    const { projectId } = await chainToInterior();
    await approvedMep(projectId);
    const first = await approvedMerge(projectId);
    // transient: TTL expired before execution → same plan again
    const e1 = await issueFor(projectId, first.reviewId, 3, "Commit #2");
    await rollbackEnvelope(e1, [{ code: "expired_ttl", message: "expired before execution" }]);
    expect((await merge(projectId)).json()).toMatchObject({ error: "merge_review_reissuable", envelope_status: "rolled_back" });
    // issue passes every chain check and stops at the executor
    expect((await issue(projectId)).json()).toEqual({ error: "no_executor_connected" });
    expect((await gw.repos.latestReviewOfKind(projectId, "commit2_failure"))).toBeNull();
    // re-issue cap: three envelopes for one review
    await rollbackEnvelope(await issueFor(projectId, first.reviewId, 4, "Commit #2"), [{ code: "expired_ttl", message: "x" }]);
    await gw.repos.recordAck(await issueFor(projectId, first.reviewId, 5, "Commit #2"), false, "bad_seq");
    const capped = await issue(projectId);
    expect(capped.json()).toEqual({ error: "merge_review_reissue_exhausted", reissues: 3 });
    expect((await gw.repos.latestReviewOfKind(projectId, "commit2_failure"))!.content).toMatchObject({ reason: "merge_review_reissue_exhausted", hard: false });

    // hard: the merged plan is wrong for this model → chain failed, never re-merged
    const { projectId: p2 } = await chainToInterior();
    await approvedMep(p2);
    const m2 = await approvedMerge(p2);
    await rollbackEnvelope(await issueFor(p2, m2.reviewId, 3, "Commit #2"), [{ op_index: 1, code: "unknown_revit_type", message: "CHPT_Pipe_PVC_DWV_PLACEHOLDER" }]);
    const failure = await gw.repos.latestReviewOfKind(p2, "commit2_failure");
    expect(failure?.status).toBe("pending");
    expect(failure!.content).toMatchObject({ reason: "executor_rejected", hard: true });
    expect((await merge(p2)).json()).toEqual({ error: "merge_chain_failed" });
    expect((await state(p2)).commit2.failed).toBe(true);
  });

  it("MergeResult provenance is verified before any card exists", async () => {
    const { projectId } = await chainToInterior();
    await approvedMep(projectId);
    // an un-actioned device moved without an action row
    mergeQueue.push({
      status: 200,
      body: (req: MergeReq) => {
        const body = defaultMerge(req) as { ops: Op[] };
        body.ops.find((o) => o.args["id"] === "E-001")!.args["offset"] = 1000;
        return body;
      },
    });
    const tampered = await merge(projectId);
    expect(tampered.statusCode).toBe(422);
    expect(tampered.json().error).toBe("merge_ops_unverified");
    expect(tampered.json().detail).toContain("E-001");
    expect((await gw.repos.latestReviewOfKind(projectId, "commit2_merge"))).toBeNull();
    let failure = await gw.repos.latestReviewOfKind(projectId, "commit2_failure");
    expect(failure!.content).toMatchObject({ reason: "merge_ops_unverified", hard: true });
    // the chain is failed now — start a fresh one to test the other verifier paths
    await approvedMep(projectId);
    mergeQueue.push({
      status: 200,
      body: (req: MergeReq) => {
        const body = defaultMerge(req) as { ops: Op[] };
        body.ops.pop(); // no trailing interference check
        return body;
      },
    });
    expect((await merge(projectId)).json().detail).toContain("run_interference_check");
    await approvedMep(projectId);
    mergeQueue.push({
      status: 200,
      body: (req: MergeReq) => {
        const body = defaultMerge(req) as { ops: Op[] };
        body.ops.splice(1, 0, { op: "create_pipe", args: { ...MEP_OPS[0]!.args, id: "P-099" } });
        return body;
      },
    });
    expect((await merge(projectId)).json().detail).toContain("P-099");
    // the service itself says REVIEW: budget_exhausted / blocked → commit2_failure, 409
    await approvedMep(projectId);
    mergeQueue.push({
      status: 200,
      body: (req: MergeReq) => ({
        ...(defaultMerge(req) as Record<string, unknown>),
        status: "blocked", ops: [], svgs: {}, blocked_reason: "F-001~F-002: same clash priority 5",
      }),
    });
    const blocked = await merge(projectId);
    expect(blocked.statusCode).toBe(409);
    expect(blocked.json()).toEqual({ error: "merge_review_required", status: "blocked" });
    failure = await gw.repos.latestReviewOfKind(projectId, "commit2_failure");
    expect(failure!.content).toMatchObject({ reason: "blocked", hard: false, blocked_reason: "F-001~F-002: same clash priority 5" });
    // a 422 from the service is a hard failure too
    await approvedMep(projectId);
    mergeQueue.push({ status: 422, body: { error: "clash_pair_unknown", message: "X-1", raw_outputs: [] } });
    expect((await merge(projectId)).json().error).toBe("clash_pair_unknown");
  });

  it("commit2 snapshot freezes the merged layout; every Commit #2 route and furnish are then 409", async () => {
    const { projectId } = await chainToInterior();
    await approvedMep(projectId);
    const m = await approvedMerge(projectId);
    const envelopeId = await issueFor(projectId, m.reviewId, 3, "Commit #2");
    expect((await planMep(projectId, CONFIRMATIONS)).json()).toMatchObject({ error: "commit2_envelope_in_flight" });
    expect((await inject({ method: "POST", url: `/projects/${projectId}/furnish-layout`, headers: svc })).json().error).toBe("commit2_envelope_in_flight");
    await commitEnvelope(envelopeId);
    const snapshot = await gw.repos.getSnapshot(projectId, "commit2");
    expect(snapshot!.seq).toBe(3);
    expect(snapshot!.layout).toEqual(((await gw.repos.getReview(m.reviewId))!.content as { layout: unknown }).layout);
    const s = await state(projectId);
    expect(s.commit2_done).toBe(true);
    expect(s.commit2.envelope_status).toBe("committed");
    expect(s.last_committed_seq).toBe(3);
    for (const route of ["plan-mep", "merge-commit2", "issue-commit2", "furnish-layout"]) {
      const res = await inject({ method: "POST", url: `/projects/${projectId}/${route}`, headers: svc, payload: {} });
      expect(res.json().error, route).toBe("commit2_already_done");
    }
    const events = await gw.pool.query(
      "SELECT payload FROM event_log WHERE project_id = $1 AND kind = 'commit2_done'", [projectId],
    );
    expect(events.rows[0].payload).toMatchObject({ merge_review_id: m.reviewId, iterations_used: 0 });
  });

  it("POST /envelopes: commit-class envelopes need an approval_ref", async () => {
    const projectId = await createProject();
    for (const payload of [
      { ops: [CHECK], commit_label: "ad hoc" },
      { ops: MEP_OPS.slice(0, 1) },
      { ops: [{ op: "set_parameter", args: { target_id: "W-001", param: "x", value: 1 } }], commit_label: "Commit #9" },
    ]) {
      const res = await inject({ method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc, payload });
      expect(res.statusCode).toBe(422);
      expect(res.json().error).toBe("approval_ref_required");
    }
  });

  // ---- clash signal plumbing ------------------------------------------------------

  it("clash_delta merges into the envelope, clamps, and is project-scoped", async () => {
    const { projectId } = await chainToInterior();
    await approvedMep(projectId);
    const m = await approvedMerge(projectId);
    const envelopeId = await issueFor(projectId, m.reviewId, 3, "Commit #2");
    expect(await gw.repos.recordClashDelta(projectId, envelopeId, [{ a_id: "revit:4711", b_id: "Q-001", kind: "hard_interference" }])).toBe(true);
    expect(await gw.repos.recordClashDelta(randomUUID(), envelopeId, [{ a_id: "X-1", b_id: "Y-1", kind: "k" }])).toBe(false);
    expect(await gw.repos.recordClashDelta(projectId, randomUUID(), [])).toBe(false);
    await rollbackEnvelope(envelopeId, INTERFERENCE);
    const env = await gw.repos.latestEnvelopeForReview(m.reviewId);
    expect(env!.clash_pairs).toEqual([
      { a_id: "revit:4711", b_id: "Q-001", kind: "hard_interference" },
      { a_id: "P-001", b_id: "E-001", kind: "hard_interference" },
    ]);
    const many = Array.from({ length: 300 }, (_, i) => ({ a_id: `E-${String(i).padStart(3, "0")}`, b_id: "P-001", kind: "k" }));
    expect(mergeClashPairs([], many)).toHaveLength(256);
    expect(clashPairsFromErrors([{ code: "interference", message: "A-1~B-2" }, { code: "other", message: "x~y" }])).toEqual([
      { a_id: "A-1", b_id: "B-2", kind: "hard_interference" },
    ]);
    expect(isHardRollback([{ code: "interference", message: "a~b" }, { code: "expired_ttl" }])).toBe(false);
    expect(isHardRollback([{ code: "unknown_host", message: "W-9" }])).toBe(true);
  });

  it("verifier: relocate_stack lets pipes move, conduits are derived, interior verbatim flag must be honest", () => {
    const base = mergeResultSchema.parse({
      ...defaultMerge({
        interior: { review_id: "i", content_hash: "1".repeat(64), ops: INTERIOR_OPS, layout: FURNISHED_LAYOUT },
        mep: { review_id: "m", content_hash: "2".repeat(64), plan: { ops: MEP_OPS } },
        iterations_used: 0, iteration: 1, prior_actions: [], clash_pairs: [],
      }),
    });
    const branches = {
      interior: { content_hash: "1".repeat(64), ops: INTERIOR_OPS },
      mep: { content_hash: "2".repeat(64), ops: MEP_OPS },
    };
    expect(verifyMergeResult(base, branches)).toEqual({ ok: true });
    const movedPipe = structuredClone(base);
    (movedPipe.ops[1]!.args["path"] as number[][])[0]![1] = 5000;
    expect(verifyMergeResult(movedPipe, branches).ok).toBe(false);
    movedPipe.actions.push({ ...base.actions[0]!, iteration: 1, trigger: "phase_a", pair: { a_id: "C-001", b_id: "P-001", kind: "phase_a_overlap" },
      lower: "P-001", lower_priority: 1, higher: "C-001", higher_priority: 0, action: "relocate_stack", params: {}, changed: true });
    expect(verifyMergeResult(movedPipe, branches)).toEqual({ ok: true });
    const rerouted = structuredClone(base);
    (rerouted.ops[3]!.args["path"] as number[][]).push([0, 3000, 2600]);
    expect(verifyMergeResult(rerouted, branches)).toEqual({ ok: true }); // conduits are derived state
    const lying = structuredClone(base);
    (lying.ops[0]!.args["center"] as number[])[0] = 1000;
    lying.actions.push({ iteration: 1, trigger: "phase_a", pair: { a_id: "C-001", b_id: "F-001", kind: "phase_a_overlap" }, lower: "F-001",
      lower_priority: 5, higher: "C-001", higher_priority: 0, action: "relegalize_furniture", params: {}, changed: true });
    expect(verifyMergeResult(lying, branches).ok).toBe(false); // ops_verbatim still true
    lying.interior.ops_verbatim = false;
    expect(verifyMergeResult(lying, branches)).toEqual({ ok: true });
    expect(verifyMergeResult(base, { ...branches, mep: { ...branches.mep, content_hash: "3".repeat(64) } }).ok).toBe(false);
  });

  // ---- a real executor: fresh seq, reissue_of, frames in both orders ---------------

  it("issue-commit2 sends the approved ops under a fresh seq; rollback + clash_delta in either order agree", async () => {
    const { projectId } = await chainToInterior();
    await approvedMep(projectId);
    const m = await approvedMerge(projectId);
    const enroll = await inject({ method: "POST", url: `/projects/${projectId}/workstations`, headers: svc, payload: { workstation_id: "ws-live-02" } });
    const token = enroll.json().token as string;
    const delivered: { payload: string }[] = [];
    const ws = await new Promise<WebSocket>((resolve, reject) => {
      const socket = new WebSocket(`ws://127.0.0.1:${port}/wss`, { headers: { authorization: `Bearer ${token}` } });
      socket.once("open", () => socket.send(JSON.stringify({
        type: "hello", workstation_id: "ws-live-02", plugin_version: "0.1.0", last_committed_seq: 2, id_map_hash: idMapHash({}),
      })));
      socket.on("message", (data) => {
        const msg = JSON.parse(data.toString()) as { type: string; payload?: string };
        if (msg.type === "auth_ok") resolve(socket);
        if (msg.type === "envelope") delivered.push({ payload: msg.payload! });
      });
      socket.once("error", reject);
    });
    try {
      const first = await issue(projectId);
      expect(first.statusCode, first.body).toBe(202);
      expect(first.json().seq).toBe(3);
      await sleep(100);
      expect(delivered).toHaveLength(1);
      const body = JSON.parse(delivered[0]!.payload) as { ops: Op[]; commit_label: string; approval_ref: { review_id: string } };
      expect(body.commit_label).toBe("Commit #2");
      expect(body.approval_ref.review_id).toBe(m.reviewId);
      expect(body.ops).toEqual(((await gw.repos.getReview(m.reviewId))!.content as { ops: Op[] }).ops); // SI-2 verbatim
      const envelopeId = first.json().envelope_id as string;
      // clash_delta BEFORE the commit_result: merged, envelope still in flight
      ws.send(JSON.stringify({ type: "clash_delta", envelope_id: envelopeId, pairs: [{ a_id: "revit:77", b_id: "Q-001", kind: "hard_interference" }] }));
      ws.send(JSON.stringify({ type: "commit_result", envelope_id: envelopeId, status: "rolled_back", id_map_delta: [], errors: INTERFERENCE }));
      await sleep(200);
      let s = await state(projectId);
      expect(s.commit2.envelope_status).toBe("rolled_back");
      expect(s.commit2.clash_pairs).toEqual([
        { a_id: "revit:77", b_id: "Q-001", kind: "hard_interference" },
        { a_id: "P-001", b_id: "E-001", kind: "hard_interference" },
      ]);
      // plan 2 → approve → re-issue under a FRESH seq (4, not 3 again), event carries reissue_of
      await approvedMerge(projectId);
      const reissue = await issue(projectId);
      expect(reissue.statusCode, reissue.body).toBe(202);
      expect(reissue.json().seq).toBe(4);
      const event = await gw.pool.query(
        "SELECT payload FROM event_log WHERE project_id = $1 AND kind = 'envelope_issued' ORDER BY ts DESC LIMIT 1", [projectId],
      );
      expect(event.rows[0].payload.reissue_of).toBeUndefined(); // a NEW review: not a re-issue of the same plan
      const envelope2 = reissue.json().envelope_id as string;
      // commit_result BEFORE clash_delta this time: same union
      ws.send(JSON.stringify({ type: "commit_result", envelope_id: envelope2, status: "rolled_back", id_map_delta: [], errors: INTERFERENCE }));
      ws.send(JSON.stringify({ type: "clash_delta", envelope_id: envelope2, pairs: [{ a_id: "revit:77", b_id: "Q-001", kind: "hard_interference" }] }));
      await sleep(200);
      s = await state(projectId);
      expect(s.commit2.clash_pairs).toEqual([
        { a_id: "P-001", b_id: "E-001", kind: "hard_interference" },
        { a_id: "revit:77", b_id: "Q-001", kind: "hard_interference" },
      ]);
      expect(s.commit2.iterations_used).toBe(1);
      expect(s.recent_envelopes.map((e: { seq: number; status: string }) => [e.seq, e.status])).toEqual([[4, "rolled_back"], [3, "rolled_back"], [2, "committed"], [1, "committed"]]);
      // same plan re-issued after a transient reject → reissue_of names the prior envelope
      const third = await approvedMerge(projectId);
      const issued3 = await issue(projectId);
      expect(issued3.json().seq).toBe(5);
      ws.send(JSON.stringify({ type: "ack", envelope_id: issued3.json().envelope_id, status: "rejected", reason: "bad_seq" }));
      await sleep(150);
      expect((await merge(projectId)).json().error).toBe("merge_review_reissuable");
      const again = await issue(projectId);
      expect(again.json().seq).toBe(6);
      const reissued = await gw.pool.query(
        "SELECT payload FROM event_log WHERE project_id = $1 AND kind = 'envelope_issued' AND payload ? 'reissue_of'", [projectId],
      );
      expect(reissued.rows).toHaveLength(1);
      expect(reissued.rows[0].payload.reissue_of).toBe(issued3.json().envelope_id);
      expect(third.body.iterations_used).toBe(2);
    } finally {
      ws.close();
    }
  });
});
