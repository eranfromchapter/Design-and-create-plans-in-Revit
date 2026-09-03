// DB-backed Phase 7 flow: render-views (the export_views envelope + the render job that
// correlates export_ready frames by order), compose-render (blobs -> the AIDM bridge ->
// render_review with refs only), finish-selection (the bridge validator -> finish_commit
// whose ops ARE the committed ops), issue-finish ("Commit #3 finishes" under approval_ref
// -> finish_selections row), the blob routes, the SI-2/SI-4 hardening on /envelopes and
// the review cards. The bridge is a stub speaking the real /render +
// /finish-selection/validate contracts; the executor is a fake over the real WSS that
// writes PNGs into BLOB_DIR by hash and emits frames like the sim. Requires DATABASE_URL.
import { createServer, type Server } from "node:http";
import { createHash, randomUUID } from "node:crypto";
import { mkdtemp, readFileSync } from "node:fs";
import { promises as fsp } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import type { InjectOptions } from "fastify";
import { WebSocket } from "ws";
import { productsCatalog } from "@chapter/contracts";
import { loadConfig, type Config } from "../src/config.js";
import { buildGateway, type Gateway } from "../src/app.js";
import { setBridgeTimeouts, BRIDGE_TIMEOUTS_DEFAULT } from "../src/render/bridge-client.js";
import { EXPORT_LABEL, FINISH_LABEL, FINISH_REISSUE_CAP, RENDER_VIEWS } from "../src/http/render.js";


const DATABASE_URL = process.env["DATABASE_URL"];
const SERVICE = "service-token-0123456789";
const ACTOR = "actor-token-eran";
const sha256 = (b: Buffer) => createHash("sha256").update(b).digest("hex");

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const GOLDEN_LAYOUT = JSON.parse(readFileSync(join(REPO, "fixtures", "layouts", "2br_golden.json"), "utf8")) as {
  meta: Record<string, unknown>;
  walls: { id: string; start: [number, number]; end: [number, number] }[];
  rooms: unknown[];
  constraints: Record<string, unknown>;
};
const FIXTURE_PNGS = ["plan", "section", "3d_hidden"].map((v) =>
  readFileSync(join(REPO, "fixtures", "renders", `phase7_2br_${v}_2048.png`)),
);

// a valid 1x1 PNG; variants append a byte so refs differ while the magic stays intact
const PNG_1x1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);
const pngVariant = (n: number): Buffer => Buffer.concat([PNG_1x1, Buffer.from([n & 0xff, (n >> 8) & 0xff])]);
const b64 = (b: Buffer) => b.toString("base64");

const HOSTILE_TAG = "<script>alert(1)</script>";
const STYLE_TAGS = ["modern", "warm minimalism", HOSTILE_TAG];

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

// the compiled layout carries rooms + style_tags: compose-render reads both from the snapshot
const NEW_LAYOUT = {
  ...GOLDEN_LAYOUT,
  meta: { ...GOLDEN_LAYOUT.meta, phase: "new", brief_version: 1 },
  rooms: [
    {
      id: "R-001", name: "Living", program: "living",
      boundary: [[0, 0], [3000, 0], [3000, 3000], [0, 3000]],
      boundary_wall_ids: ["W-001", "W-002", "W-003"],
    },
    {
      id: "R-002", name: "Bath", program: "bathroom",
      boundary: [[3000, 0], [5000, 0], [5000, 2000], [3000, 2000]],
      boundary_wall_ids: ["W-003", "W-004", "W-005"],
    },
  ],
  constraints: { style_tags: STYLE_TAGS },
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
  id: "F-001", kind: "table",
  revit_family: "CHPT_Nightstand_PLACEHOLDER", revit_type: "Nightstand_450x450_PLACEHOLDER",
  center: [3500.0, 271.0], rotation_deg: 0, footprint: [450, 450], clearance_front: 0, wall_seeking: true,
};
const FURNISHED_LAYOUT = { ...NEW_LAYOUT, furniture: [{ room_id: "R-001", items: [PLACED_ITEM] }] };
const INTERIOR_OPS = [
  { op: "place_family", args: {
    id: "F-001", revit_family: "CHPT_Nightstand_PLACEHOLDER", revit_type: "Nightstand_450x450_PLACEHOLDER",
    center: [3500.0, 271.0], rotation_deg: 0, footprint: [450, 450], level: "Level 1",
  } },
];
function furnishResult(): Record<string, unknown> {
  return {
    layout: FURNISHED_LAYOUT, ops: INTERIOR_OPS,
    svgs: { commit1: "<svg>commit1</svg>", furnished: "<svg>furnished</svg>" }, unplaced: [],
    diagnostics: { attempts: 1, repair_retried: false, elapsed_ms: 1, items: [], total_candidates: 1, spiral_total: 0, walls_tried: 1 },
  };
}
type Op = { op: string; args: Record<string, unknown> };
const MEP_OPS: Op[] = [
  { op: "place_device", args: { id: "E-001", kind: "receptacle", host_wall_id: "W-001", offset: 1912.5, height_afl: 380, face: "right" } },
];
const CHECK: Op = { op: "run_interference_check", args: { scope: "last_commit" } };
function mepPlan(): Record<string, unknown> {
  return {
    layout: FURNISHED_LAYOUT, inputs: { panel: [50, 3000], levels_source: "confirmation" },
    stacks: [], branches: [], fixture_routes: [],
    devices: [{ id: "E-001", kind: "receptacle", rule: "E-1", room_id: "R-001", host_wall_id: "W-001", offset: 1912.5, height_afl: 380, face: "right" }],
    home_runs: [], ops: MEP_OPS, review_items: [], blocking: [],
    svgs: { furnished: "<svg>f</svg>", mep: "<svg>m</svg>" }, diagnostics: { elapsed_ms: 1, counters: {} },
    counts: { devices: 1, receptacle: 1, gfci: 0, switch: 0, receptacle_240: 0, pipes: 0, stacks: 0, conduits: 0, review_items: 0, blocking: 0, extensions: { appliance: 0 } },
  };
}
function mergeResult(req: { interior: { review_id: string; content_hash: string; ops: Op[]; layout: unknown }; mep: { review_id: string; content_hash: string }; iteration: number; iterations_used: number }): Record<string, unknown> {
  const ops = [...req.interior.ops, ...MEP_OPS, CHECK];
  return {
    status: "clean", iteration: req.iteration, iterations_used: req.iterations_used,
    interior: { review_id: req.interior.review_id, content_hash: req.interior.content_hash, ops_count: req.interior.ops.length, ops_verbatim: true },
    mep: { review_id: req.mep.review_id, content_hash: req.mep.content_hash, ops_count: MEP_OPS.length },
    layout: req.interior.layout, ops, actions: [], replan_deltas: [], dropped: [],
    clash_report: { budget: { limit: 3, used: 0, remaining: 3 }, phase_a: { rounds: [] }, phase_b: { replans: [] }, prisms: {}, open_clashes: [], status: "clean" },
    svgs: { commit1: "<svg>c1</svg>", merged: "<svg>merged</svg>" }, blocked_reason: null,
    counts: { ops: ops.length },
  };
}

// ---- the bridge stub ---------------------------------------------------------------

interface RenderReq {
  project_id: string; render_id: string;
  views: { name: string; kind: string; px: number; png_base64: string }[];
  style_tags: string[]; finish_tier: string; rooms: { id: string; name: string; program: string }[];
  allow_placeholders: boolean;
}
interface ValidateReq {
  project_id: string; layout: unknown; id_map_ids: string[]; finish_tier: string; catalog_version: string;
  render_ref: string | null; selection: { rooms?: { room_id: string; wall_sku?: string }[]; doors?: { id: string; sku: string }[] };
  allow_placeholders: boolean;
}
const WALL_SKU = "CHPT-WALL-PAINT-STD_PLACEHOLDER";
const DOOR_SKU = "CHPT-DOOR-SC-STD_PLACEHOLDER";

function defaultRender(req: RenderReq): Record<string, unknown> {
  const tags = req.style_tags.filter((t) => t !== HOSTILE_TAG).sort();
  return {
    control_maps: req.views.map((v, i) => ({
      name: v.name, kind: v.kind,
      canny_png_base64: b64(pngVariant(10 + i)), lines_png_base64: b64(pngVariant(20 + i)), preview_png_base64: b64(pngVariant(30 + i)),
      stats: { edge_px: 1000 + i, line_count: 10 + i, width: v.px, height: 1350 },
    })),
    prompt: {
      template_version: "phase7-v1",
      text: `Photorealistic ... <style_tags>\n${tags.join(", ")}\n</style_tags> ...`,
      tags_used: tags,
      tags_dropped: req.style_tags.filter((t) => t === HOSTILE_TAG).map((t) => ({ tag: t, reason: "not_in_vocabulary" })),
    },
    renders: req.views.map((v, i) => ({
      name: v.name, provider: "mock", png_base64: b64(pngVariant(40 + i)), ref: `mock-${req.render_id}-${v.name}`, status: "ok", attempts: 1,
    })),
    candidates: {
      wall: [productsCatalog.skus.find((s) => s.sku === WALL_SKU)],
      door: [productsCatalog.skus.find((s) => s.sku === DOOR_SKU)],
      casework: [], plumbing_fixture: [],
    },
    review_items: req.style_tags.includes(HOSTILE_TAG)
      ? [{ code: "style_tag_dropped", severity: "info", refs: [HOSTILE_TAG], message: "style tag dropped: not_in_vocabulary" }]
      : [],
    diagnostics: { elapsed_ms: 3, provider: "mock", opencv_version: "4.14.0", catalog_version: productsCatalog.catalog_version, views: [] },
  };
}

function defaultValidate(req: ValidateReq): Record<string, unknown> {
  const ops: Op[] = [];
  const targets = new Set<string>();
  for (const d of req.selection.doors ?? []) {
    targets.add(d.id);
    ops.push({ op: "set_parameter", args: { target_id: d.id, param: "CHPT_Product_SKU", value: d.sku } });
    ops.push({ op: "set_parameter", args: { target_id: d.id, param: "CHPT_Spec_Section", value: "08 14 16" } });
  }
  for (const r of req.selection.rooms ?? []) {
    if (!r.wall_sku) continue;
    for (const w of ["W-001", "W-002"]) {
      if (targets.has(w)) continue;
      targets.add(w);
      ops.push({ op: "set_parameter", args: { target_id: w, param: "CHPT_Finish_Material", value: "Placeholder Mfg PH-02" } });
      ops.push({ op: "set_parameter", args: { target_id: w, param: "CHPT_Product_SKU", value: r.wall_sku } });
      if (req.render_ref) ops.push({ op: "set_parameter", args: { target_id: w, param: "CHPT_Render_Ref", value: req.render_ref } });
      ops.push({ op: "set_parameter", args: { target_id: w, param: "CHPT_Spec_Section", value: "09 91 23" } });
    }
  }
  ops.sort((a, b) => String(a.args["target_id"]).localeCompare(String(b.args["target_id"])) || String(a.args["param"]).localeCompare(String(b.args["param"])));
  return {
    ops, review_items: [], blocking: [],
    diagnostics: { per_target: {}, counts: { ops: ops.length, targets: targets.size, walls_applied: 2, walls_conflict: 0, blocking: 0, info: 0 } },
  };
}

type Canned = { status: number; body: unknown | ((req: never) => unknown); delayMs?: number };
const renderQueue: Canned[] = [];
const validateQueue: Canned[] = [];
const renderRequests: RenderReq[] = [];
const validateRequests: ValidateReq[] = [];
let services: Server;
let servicesUrl: string;

describe.skipIf(!DATABASE_URL)("gateway Phase 7 flow (DB-backed)", () => {
  let gw: Gateway;
  let gwOff: Gateway; // no BLOB_DIR, no AIDM_BRIDGE_URL
  let config: Config;
  let port: number;
  let blobDir: string;

  beforeAll(async () => {
    services = createServer((req, res) => {
      let raw = "";
      req.on("data", (c) => (raw += c));
      req.on("end", () => {
        const parsed = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
        let canned: Canned;
        if (req.url === "/render") {
          renderRequests.push(parsed as unknown as RenderReq);
          canned = renderQueue.shift() ?? { status: 200, body: defaultRender };
        } else if (req.url === "/finish-selection/validate") {
          validateRequests.push(parsed as unknown as ValidateReq);
          canned = validateQueue.shift() ?? { status: 200, body: defaultValidate };
        } else if (req.url === "/plan-mep") {
          canned = { status: 200, body: mepPlan() };
        } else if (req.url === "/merge") {
          canned = { status: 200, body: mergeResult(parsed as never) };
        } else if (req.url === "/furnish") {
          canned = { status: 200, body: furnishResult() };
        } else if (req.url === "/compile") {
          canned = { status: 200, body: compileResult() };
        } else {
          canned = { status: 200, body: { review_payload: scanReviewPayload() } };
        }
        const body = typeof canned.body === "function" ? (canned.body as (r: unknown) => unknown)(parsed) : canned.body;
        const finish = () => {
          res.writeHead(canned.status, { "content-type": "application/json" });
          res.end(JSON.stringify(body));
        };
        if (canned.delayMs) setTimeout(finish, canned.delayMs);
        else finish();
      });
    });
    await new Promise<void>((resolve) => services.listen(0, "127.0.0.1", resolve));
    const address = services.address();
    if (typeof address === "string" || !address) throw new Error("no stub port");
    servicesUrl = `http://127.0.0.1:${address.port}`;
    blobDir = await new Promise<string>((resolve, reject) =>
      mkdtemp(join(tmpdir(), "chapter-gw-blobs-"), (err, dir) => (err ? reject(err) : resolve(dir))),
    );

    config = loadConfig({
      DATABASE_URL: DATABASE_URL!,
      ENVELOPE_MASTER_KEY: "07".repeat(32),
      SERVICE_TOKEN: SERVICE,
      ACTOR_TOKENS: `${ACTOR}:eran@hellochapter.com`,
      PORT: "0",
      SCAN_CONVERTER_URL: servicesUrl,
      LAYOUT_COMPILER_URL: servicesUrl,
      AIDM_BRIDGE_URL: servicesUrl,
      BLOB_DIR: blobDir,
    });
    gw = await buildGateway(config, { logger: false });
    const baseUrl = await gw.app.listen({ port: 0, host: "127.0.0.1" });
    port = Number(new URL(baseUrl).port);
    gwOff = await buildGateway(
      loadConfig({
        DATABASE_URL: DATABASE_URL!, ENVELOPE_MASTER_KEY: "07".repeat(32), SERVICE_TOKEN: SERVICE,
        ACTOR_TOKENS: `${ACTOR}:eran@hellochapter.com`, PORT: "0", SCAN_CONVERTER_URL: servicesUrl, LAYOUT_COMPILER_URL: servicesUrl,
      }),
      { logger: false },
    );
  });

  afterAll(async () => {
    await gw.app.close();
    await gw.pool.end();
    await gwOff.app.close();
    await gwOff.pool.end();
    await new Promise((resolve) => services.close(resolve));
    await fsp.rm(blobDir, { recursive: true, force: true });
  });

  beforeEach(async () => {
    renderQueue.length = 0;
    validateQueue.length = 0;
    renderRequests.length = 0;
    validateRequests.length = 0;
    setBridgeTimeouts({ ...BRIDGE_TIMEOUTS_DEFAULT });
    await gw.pool.query(
      "TRUNCATE finish_selections, render_jobs, layout_snapshots, briefs, reviews, id_map, event_log, envelopes, workstations, projects",
    );
  });

  const inject = (opts: InjectOptions) => gw.app.inject(opts);
  const svc = { authorization: `Bearer ${SERVICE}` };
  const actor = { authorization: `Bearer ${ACTOR}` };
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  async function waitFor(pred: () => Promise<boolean>, what: string, ms = 5000): Promise<void> {
    const until = Date.now() + ms;
    while (Date.now() < until) {
      if (await pred()) return;
      await sleep(25);
    }
    throw new Error(`timed out waiting for ${what}`);
  }

  async function createProject(): Promise<string> {
    const res = await inject({ method: "POST", url: "/projects", headers: svc, payload: { name: "phase7" } });
    return res.json().id as string;
  }
  async function approve(reviewId: string): Promise<void> {
    const res = await inject({ method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor, payload: {} });
    expect(res.statusCode, res.body).toBe(200);
  }
  async function reject(reviewId: string): Promise<void> {
    const res = await inject({ method: "POST", url: `/reviews/${reviewId}/reject`, headers: actor, payload: {} });
    expect(res.statusCode, res.body).toBe(200);
  }
  async function issueFor(projectId: string, reviewId: string | null, seq: number, label: string, opts?: { ttlS?: number; issuedAt?: Date }): Promise<string> {
    const review = reviewId ? await gw.repos.getReview(reviewId) : null;
    const envelopeId = randomUUID();
    await gw.repos.insertIssuedEnvelope({
      envelopeId, projectId, workstationId: "ws-design-01", seq,
      payload: JSON.stringify({ ttl_s: opts?.ttlS ?? 600 }), sig: "0".repeat(128),
      commitLabel: label,
      approvalRef: review ? { review_id: review.id, content_hash: review.content_hash } : undefined,
      issuedAt: (opts?.issuedAt ?? new Date()).toISOString(),
    });
    return envelopeId;
  }
  const commitEnvelope = (envelopeId: string, delta: { logical_id: string; element_id: number }[] = []) =>
    gw.repos.recordCommitResult({ envelopeId, committed: true, idMapDelta: delta, errors: [] });

  async function commit0(projectId: string): Promise<void> {
    const upload = await inject({ method: "POST", url: `/projects/${projectId}/scan-bundles`, headers: svc,
      payload: { dxf_base64: Buffer.from("stub").toString("base64") } });
    const reviewId = upload.json().review_id as string;
    await inject({ method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor, payload: { confirmations: { ceiling_height_mm: 2700 } } });
    await inject({ method: "POST", url: `/projects/${projectId}/workstations`, headers: svc, payload: { workstation_id: "ws-design-01" } });
    // the id-map carries the elements finish targets must exist in
    await commitEnvelope(await issueFor(projectId, reviewId, 1, "Commit #0"), [
      { logical_id: "W-001", element_id: 1001 }, { logical_id: "W-002", element_id: 1002 }, { logical_id: "D-001", element_id: 2001 },
    ]);
  }
  async function confirmedBrief(projectId: string, extra: Record<string, unknown> = {}): Promise<void> {
    const { review } = await gw.repos.createBriefWithReview(
      projectId, { meta: { project_id: projectId, brief_version: 1, source_sessions: ["s1"] }, ...extra }, {}, false,
    );
    await approve(review.id);
  }
  async function commit1(projectId: string): Promise<void> {
    const res = await inject({ method: "POST", url: `/projects/${projectId}/compile-layout`, headers: svc });
    expect(res.statusCode, res.body).toBe(201);
    const reviewId = res.json().review_id as string;
    await approve(reviewId);
    await commitEnvelope(await issueFor(projectId, reviewId, 2, "Commit #1"));
  }
  /** Phases 0–4 through repos + stubs: the Phase 7 precondition (Phase 7 depends on Phase 4 only). */
  async function chainToCommit1(brief: Record<string, unknown> = {}): Promise<string> {
    const projectId = await createProject();
    await commit0(projectId);
    await confirmedBrief(projectId, brief);
    await commit1(projectId);
    return projectId;
  }
  async function chainToCommit2(): Promise<string> {
    const projectId = await chainToCommit1();
    const furnish = await inject({ method: "POST", url: `/projects/${projectId}/furnish-layout`, headers: svc });
    await approve(furnish.json().review_id as string);
    const mep = await inject({ method: "POST", url: `/projects/${projectId}/plan-mep`, headers: svc,
      payload: { confirmations: { panel: [50, 3000], slab_to_slab_mm: 3000 } } });
    expect(mep.statusCode, mep.body).toBe(201);
    await approve(mep.json().review_id as string);
    const merge = await inject({ method: "POST", url: `/projects/${projectId}/merge-commit2`, headers: svc });
    expect(merge.statusCode, merge.body).toBe(201);
    await approve(merge.json().review_id as string);
    await commitEnvelope(await issueFor(projectId, merge.json().review_id as string, 3, "Commit #2"));
    return projectId;
  }

  // ---- the fake executor over the real WSS -------------------------------------------

  type Frame = Record<string, unknown>;
  interface EnvelopeBody { envelope_id: string; seq: number; ops: Op[]; commit_label?: string; approval_ref?: { review_id: string; content_hash: string } }
  interface Executor {
    ws: WebSocket;
    token: string;
    delivered: EnvelopeBody[];
    send: (frame: Frame) => void;
    close: () => Promise<void>;
  }
  /** Connects a workstation, replays hello from the gateway's own truth, and answers
   *  envelopes through `script` (default: ack, commit, and for export_views write the PNGs
   *  by hash into BLOB_DIR then emit one export_ready per view IN ORDER). */
  async function connectExecutor(
    projectId: string,
    script?: (body: EnvelopeBody, defaults: () => Promise<Frame[]>) => Promise<Frame[]>,
    pngs: Buffer[] = FIXTURE_PNGS,
  ): Promise<Executor> {
    const enroll = await inject({ method: "POST", url: `/projects/${projectId}/workstations`, headers: svc, payload: { workstation_id: `ws-live-${randomUUID().slice(0, 8)}` } });
    const token = enroll.json().token as string;
    const workstationId = enroll.json().workstation_id as string;
    const delivered: EnvelopeBody[] = [];
    const seq = await gw.repos.lastCommittedSeq(projectId);
    const hash = await gw.repos.gatewayIdMapHash(projectId);
    const attempt = () => new Promise<WebSocket>((resolve, rejectWs) => {
      const socket = new WebSocket(`ws://127.0.0.1:${port}/wss`, { headers: { authorization: `Bearer ${token}` } });
      socket.once("open", () => socket.send(JSON.stringify({
        type: "hello", workstation_id: workstationId, plugin_version: "0.1.0", last_committed_seq: seq, id_map_hash: hash,
      })));
      socket.on("message", (data) => {
        const msg = JSON.parse(data.toString()) as { type: string; payload?: string };
        if (msg.type === "auth_ok") resolve(socket);
        if (msg.type === "envelope") {
          const body = JSON.parse(msg.payload!) as EnvelopeBody;
          delivered.push(body);
          const defaults = async (): Promise<Frame[]> => {
            const frames: Frame[] = [
              { type: "ack", envelope_id: body.envelope_id, status: "accepted" },
              { type: "commit_result", envelope_id: body.envelope_id, status: "committed", id_map_delta: [], errors: [] },
            ];
            for (const op of body.ops) {
              if (op.op !== "export_views") continue;
              const views = op.args["views"] as { name: string }[];
              for (let i = 0; i < views.length; i++) {
                const bytes = pngs[i % pngs.length]!;
                const ref = sha256(bytes);
                await fsp.writeFile(join(blobDir, ref), bytes);
                frames.push({ type: "export_ready", kind: "view", blob_ref: ref });
              }
            }
            return frames;
          };
          void (script ? script(body, defaults) : defaults()).then((frames) => {
            for (const f of frames) socket.send(JSON.stringify(f));
          });
        }
      });
      socket.once("error", rejectWs);
    });
    let ws: WebSocket | null = null;
    for (let tries = 0; ws === null; tries++) {
      try {
        ws = await attempt();
      } catch (err) {
        // one executor per project: the previous socket's server-side close can lag ours
        if (tries >= 40) throw err;
        await sleep(50);
      }
    }
    return {
      ws, token, delivered,
      send: (frame) => ws.send(JSON.stringify(frame)),
      close: () => new Promise<void>((resolve) => { ws.once("close", () => resolve()); ws.close(); }),
    };
  }

  const renderViews = (projectId: string) => inject({ method: "POST", url: `/projects/${projectId}/render-views`, headers: svc });
  const compose = (projectId: string) => inject({ method: "POST", url: `/projects/${projectId}/compose-render`, headers: svc });
  const finishSelection = (projectId: string, payload: Record<string, unknown>, headers: Record<string, string> = svc) =>
    inject({ method: "POST", url: `/projects/${projectId}/finish-selection`, headers, payload });
  const issueFinish = (projectId: string) => inject({ method: "POST", url: `/projects/${projectId}/issue-finish`, headers: svc });
  const state = async (projectId: string) =>
    (await inject({ method: "GET", url: `/projects/${projectId}/state`, headers: svc })).json();
  const events = async (projectId: string, kind: string) =>
    (await gw.pool.query("SELECT payload FROM event_log WHERE project_id = $1 AND kind = $2 ORDER BY id", [projectId, kind])).rows.map((r) => r.payload as Record<string, unknown>);
  const SELECTION = { rooms: [{ room_id: "R-001", wall_sku: WALL_SKU }], doors: [{ id: "D-001", sku: DOOR_SKU }] };

  /** Chain to an exported job: render-views + the executor's frames. */
  async function exported(projectId: string, executor?: Executor): Promise<{ renderId: string; executor: Executor }> {
    const exec = executor ?? (await connectExecutor(projectId));
    const res = await renderViews(projectId);
    expect(res.statusCode, res.body).toBe(202);
    const renderId = res.json().render_id as string;
    await waitFor(async () => (await state(projectId)).render_exported === true, "render_exported");
    return { renderId, executor: exec };
  }
  async function approvedRender(projectId: string, executor?: Executor): Promise<{ renderId: string; reviewId: string; executor: Executor }> {
    const { renderId, executor: exec } = await exported(projectId, executor);
    const res = await compose(projectId);
    expect(res.statusCode, res.body).toBe(201);
    const reviewId = res.json().review_id as string;
    await approve(reviewId);
    return { renderId, reviewId, executor: exec };
  }

  // ---- render-views -----------------------------------------------------------------

  it("render-views ladder: 404, commit0/commit1, no executor, envelope_in_flight, render_export_in_progress", async () => {
    expect((await renderViews(randomUUID())).statusCode).toBe(404);
    const projectId = await createProject();
    expect((await renderViews(projectId)).json().error).toBe("commit0_not_done");
    await commit0(projectId);
    expect((await renderViews(projectId)).json().error).toBe("commit1_not_done");
    await confirmedBrief(projectId);
    await commit1(projectId);
    expect((await renderViews(projectId)).json().error).toBe("no_executor_connected");
    const other = await issueFor(projectId, null, 3, "ad hoc");
    expect((await renderViews(projectId)).json()).toEqual({ error: "envelope_in_flight", envelope_id: other });
    await gw.repos.recordAck(other, false, "bad_seq");
    // hold the executor's answer so the export envelope stays in flight
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const executor = await connectExecutor(projectId, async (_body, defaults) => { await gate; return defaults(); });
    try {
      const res = await renderViews(projectId);
      expect(res.statusCode, res.body).toBe(202);
      expect(res.json().seq).toBe(3); // export consumes a seq (Phase 6 chain ends at 2 here)
      const renderId = res.json().render_id as string;
      const job = await gw.repos.getRenderJob(renderId);
      expect(job).toMatchObject({ status: "exporting", expected_views: 3, blob_refs: [null, null, null], envelope_id: res.json().envelope_id });
      expect(job!.views).toEqual(RENDER_VIEWS);
      const again = await renderViews(projectId);
      expect(again.json()).toEqual({ error: "render_export_in_progress", envelope_id: res.json().envelope_id });
      expect((await compose(projectId)).json()).toMatchObject({ error: "render_export_in_progress", attached: 0, expected: 3 });
      const s = await state(projectId);
      expect(s.render).toMatchObject({ render_id: renderId, status: "exporting", envelope_status: "issued", blob_refs: 0 });
      expect(s.render_exported).toBe(false);
      // the envelope is NOT commit-class: no approval_ref, label "Export views", one export_views op
      const body = executor.delivered[0]!;
      expect(body.commit_label).toBe(EXPORT_LABEL);
      expect(body.approval_ref).toBeUndefined();
      expect(body.ops).toEqual([{ op: "export_views", args: { views: RENDER_VIEWS } }]);
      release();
      await waitFor(async () => (await state(projectId)).render_exported === true, "render_exported");
      const done = (await gw.repos.getRenderJob(renderId))!;
      expect(done.status).toBe("exported");
      expect(done.blob_refs).toEqual(FIXTURE_PNGS.map(sha256)); // correlated BY ORDER: plan, section, 3d_hidden
      expect(await events(projectId, "render_exported")).toHaveLength(1);
      expect((await events(projectId, "render_job_created"))[0]).toMatchObject({ render_id: renderId, views: ["plan", "section", "3d_hidden"] });
      // a second export is a NEW job; the exported one is not superseded
      const second = await renderViews(projectId);
      expect(second.statusCode).toBe(202);
      expect(second.json().seq).toBe(4);
      await waitFor(async () => (await gw.repos.latestRenderJob(projectId))!.status === "exported", "second export");
      expect((await gw.repos.getRenderJob(renderId))!.status).toBe("exported");
      expect((await state(projectId)).render.render_id).toBe(second.json().render_id);
    } finally {
      await executor.close();
    }
  });

  it("correlation: identical refs fill distinct slots; extra, bad and unmatched frames are events only", async () => {
    const projectId = await chainToCommit1();
    const same = pngVariant(7);
    const executor = await connectExecutor(projectId, undefined, [same]);
    try {
      const { renderId } = await exported(projectId, executor);
      const job = (await gw.repos.getRenderJob(renderId))!;
      expect(job.blob_refs).toEqual([sha256(same), sha256(same), sha256(same)]);
      // a 4th frame after completion: no exporting job -> unmatched
      executor.send({ type: "export_ready", kind: "view", blob_ref: sha256(same) });
      await waitFor(async () => (await events(projectId, "export_ready_unmatched")).length === 1, "unmatched");
      expect((await events(projectId, "export_ready_unmatched"))[0]).toMatchObject({ reason: "no_exporting_job" });
      // a ref outside the sha256 pattern (still inside the wire charset)
      executor.send({ type: "export_ready", kind: "view", blob_ref: "not-a-sha" });
      await waitFor(async () => (await events(projectId, "export_ready_bad_ref")).length === 1, "bad ref");
      // other kinds stay event-only
      executor.send({ type: "export_ready", kind: "parameters", blob_ref: sha256(same) });
      await waitFor(async () => (await events(projectId, "export_ready")).some((e) => e["kind"] === "parameters"), "parameters frame");
      expect((await gw.repos.getRenderJob(renderId))!.status).toBe("exported"); // untouched
    } finally {
      await executor.close();
    }
  });

  it("correlation: a 4th view frame never touches the completed job; a frame before the commit_result is unmatched", async () => {
    const projectId = await chainToCommit1();
    // first envelope: one frame too many — completion already flipped the job to exported,
    // so the extra frame finds no exporting job (export_ready_extra needs the named-slot
    // path of gate question G1)
    const executor = await connectExecutor(projectId, async (body, defaults) => {
      const frames = await defaults();
      return [...frames, { type: "export_ready", kind: "view", blob_ref: sha256(pngVariant(99)) }];
    });
    try {
      const { renderId } = await exported(projectId, executor);
      await waitFor(async () => (await events(projectId, "export_ready_unmatched")).length === 1, "extra frame");
      expect((await events(projectId, "export_ready_unmatched"))[0]).toMatchObject({ reason: "no_exporting_job", blob_ref: sha256(pngVariant(99)) });
      expect((await gw.repos.getRenderJob(renderId))!.blob_refs).toEqual(FIXTURE_PNGS.map(sha256));
    } finally {
      await executor.close();
    }
    // second envelope: frames BEFORE the commit_result land nowhere (the sim never does this;
    // this pins the contract's order dependency — gate question G1)
    const early = await connectExecutor(projectId, async (body, defaults) => {
      const frames = await defaults();
      const ready = frames.filter((f) => f["type"] === "export_ready");
      const rest = frames.filter((f) => f["type"] !== "export_ready");
      return [ready[0]!, ...rest, ...ready.slice(1)];
    });
    try {
      const res = await renderViews(projectId);
      expect(res.statusCode, res.body).toBe(202);
      const renderId = res.json().render_id as string;
      await waitFor(async () => (await events(projectId, "export_ready_unmatched")).some((e) => e["reason"] === "envelope_not_committed"), "early frame");
      expect((await events(projectId, "export_ready_unmatched"))).toHaveLength(2); // the extra + the early one
      await waitFor(async () => ((await gw.repos.getRenderJob(renderId))!.blob_refs.filter(Boolean).length === 2), "two late frames");
      const job = (await gw.repos.getRenderJob(renderId))!;
      expect(job.status).toBe("exporting"); // incomplete forever: the first view is missing
      expect(job.blob_refs).toEqual([sha256(FIXTURE_PNGS[1]!), sha256(FIXTURE_PNGS[2]!), null]);
      expect((await compose(projectId)).json()).toMatchObject({ error: "render_export_in_progress", attached: 2 });
      // a new render-views supersedes the stuck job once its envelope has resolved
      const next = await renderViews(projectId);
      expect(next.statusCode, next.body).toBe(202);
      expect((await gw.repos.getRenderJob(renderId))!.status).toBe("failed");
      expect((await events(projectId, "render_job_superseded"))[0]).toMatchObject({ render_id: renderId });
    } finally {
      await early.close();
    }
  });

  it("export failures: rollback, ack-reject and TTL expiry fail the job; compose says render_export_failed", async () => {
    const projectId = await chainToCommit1();
    const rollback = await connectExecutor(projectId, async (body) => [
      { type: "ack", envelope_id: body.envelope_id, status: "accepted" },
      { type: "commit_result", envelope_id: body.envelope_id, status: "rolled_back", id_map_delta: [], errors: [{ op_index: 0, code: "view_export_failed", message: "no level" }] },
    ]);
    try {
      const res = await renderViews(projectId);
      expect(res.statusCode, res.body).toBe(202);
      await waitFor(async () => (await gw.repos.getRenderJob(res.json().render_id as string))!.status === "failed", "failed job");
      expect((await events(projectId, "render_export_failed"))[0]).toMatchObject({ render_id: res.json().render_id, cause: "rolled_back" });
      expect((await compose(projectId)).json()).toEqual({ error: "render_export_failed", render_id: res.json().render_id });
      expect((await state(projectId)).render).toMatchObject({ status: "failed", envelope_status: "rolled_back" });
    } finally {
      await rollback.close();
    }
    const rejecting = await connectExecutor(projectId, async (body) => [
      { type: "ack", envelope_id: body.envelope_id, status: "rejected", reason: "bad_seq" },
    ]);
    try {
      const res = await renderViews(projectId);
      expect(res.statusCode, res.body).toBe(202);
      await waitFor(async () => (await gw.repos.getRenderJob(res.json().render_id as string))!.status === "failed", "failed job");
      expect((await events(projectId, "render_export_failed")).at(-1)).toMatchObject({ cause: "ack_rejected" });
    } finally {
      await rejecting.close();
    }
    // expiry: an export envelope issued long ago with a short TTL
    const stale = await issueFor(projectId, null, 3, EXPORT_LABEL, { ttlS: 10, issuedAt: new Date(Date.now() - 60_000) });
    const renderId = randomUUID();
    await gw.repos.createRenderJob({ renderId, projectId, envelopeId: stale, views: RENDER_VIEWS });
    expect(await gw.repos.expireStaleEnvelopes()).toBeGreaterThanOrEqual(1);
    expect((await gw.repos.getRenderJob(renderId))!.status).toBe("failed");
    expect((await events(projectId, "render_export_failed")).at(-1)).toMatchObject({ render_id: renderId, cause: "expired" });
  });

  // ---- compose-render ---------------------------------------------------------------

  it("compose ladder: 503s without bridge/blob store, no_render_job, blob_missing, blob_not_png", async () => {
    const projectId = await chainToCommit1();
    const off = await gwOff.app.inject({ method: "POST", url: `/projects/${projectId}/compose-render`, headers: svc });
    expect(off.statusCode).toBe(503);
    expect(off.json().error).toBe("aidm_bridge_unavailable");
    expect((await compose(randomUUID())).statusCode).toBe(404);
    expect((await compose(projectId)).json()).toEqual({ error: "no_render_job" });
    const { renderId, executor } = await exported(projectId);
    try {
      const job = (await gw.repos.getRenderJob(renderId))!;
      const ref = job.blob_refs[1]!;
      const path = join(blobDir, ref);
      const original = await fsp.readFile(path);
      await fsp.unlink(path);
      expect((await compose(projectId)).json()).toEqual({ error: "blob_missing", render_id: renderId, index: 1, blob_ref: ref });
      await fsp.writeFile(path, Buffer.from('{"not":"png"}'));
      expect((await compose(projectId)).json()).toEqual({ error: "blob_not_png", blob_ref: ref });
      await fsp.writeFile(path, original);
      expect(renderRequests).toHaveLength(0); // the bridge was never called
      expect((await compose(projectId)).statusCode).toBe(201);
    } finally {
      await executor.close();
    }
  });

  it("compose: refs only (no base64), every ref GET-able as PNG with sha256 == ref, request carries tags/rooms/tier, review lifecycle", async () => {
    const projectId = await chainToCommit1({ finish_tier: "premium" });
    const { renderId, executor } = await exported(projectId);
    try {
      const res = await compose(projectId);
      expect(res.statusCode, res.body).toBe(201);
      expect(res.json().counts).toEqual({ views: 3, renders_ok: 3, candidates: 2, review_items: 1, tags_used: 2, tags_dropped: 1 });
      const review = (await gw.repos.getReview(res.json().review_id as string))!;
      expect(review.kind).toBe("render_review");
      expect(review.status).toBe("pending");
      const json = JSON.stringify(review.content);
      expect(json).not.toContain("_base64");
      const content = review.content as {
        render_id: string; export_envelope_id: string; layout_snapshot: string; finish_tier: string; brief_version: number;
        control_maps: { name: string; canny_ref: string; lines_ref: string; preview_ref: string; stats: { edge_px: number } }[];
        renders: { name: string; provider: string; ref: string; status: string; blob_ref: string }[];
        prompt: { tags_used: string[]; tags_dropped: { tag: string }[] }; candidates: Record<string, unknown[]>;
        source_blob_refs: string[]; catalog_version: string;
      };
      expect(content.render_id).toBe(renderId);
      expect(content.layout_snapshot).toBe("commit1");
      expect(content.finish_tier).toBe("premium");
      expect(content.brief_version).toBe(1);
      expect(content.catalog_version).toBe(productsCatalog.catalog_version);
      expect(content.source_blob_refs).toEqual(FIXTURE_PNGS.map(sha256));
      expect(content.control_maps.map((m) => m.name)).toEqual(["plan", "section", "3d_hidden"]);
      expect(content.renders.map((r) => r.ref)).toEqual(["plan", "section", "3d_hidden"].map((v) => `mock-${renderId}-${v}`));
      // every stored ref serves PNG bytes whose hash IS the ref
      const refs = [
        ...content.control_maps.flatMap((m) => [m.canny_ref, m.lines_ref, m.preview_ref]),
        ...content.renders.map((r) => r.blob_ref),
      ];
      expect(new Set(refs).size).toBe(refs.length);
      for (const ref of refs) {
        const got = await inject({ method: "GET", url: `/projects/${projectId}/blobs/${ref}`, headers: svc });
        expect(got.statusCode).toBe(200);
        expect(got.headers["content-type"]).toBe("image/png");
        expect(sha256(got.rawPayload)).toBe(ref);
      }
      // the bridge saw the snapshot's rooms + style tags (DATA) and the brief's tier
      const sent = renderRequests[0]!;
      expect(sent.render_id).toBe(renderId);
      expect(sent.style_tags).toEqual(STYLE_TAGS);
      expect(sent.rooms).toEqual([{ id: "R-001", name: "Living", program: "living" }, { id: "R-002", name: "Bath", program: "bathroom" }]);
      expect(sent.finish_tier).toBe("premium");
      expect(sent.allow_placeholders).toBe(false);
      expect(sent.views.map((v) => v.name)).toEqual(["plan", "section", "3d_hidden"]);
      expect(Buffer.from(sent.views[0]!.png_base64, "base64").equals(FIXTURE_PNGS[0]!)).toBe(true);
      // lifecycle: pending -> render_review_pending; approved -> render_already_composed + ready
      expect((await gw.repos.getRenderJob(renderId))!.status).toBe("composed");
      expect((await compose(projectId)).json()).toEqual({ error: "render_review_pending", review_id: review.id });
      let s = await state(projectId);
      expect(s.render_review_ready).toBe(false);
      expect(s.render).toMatchObject({ status: "composed", render_review_id: review.id, render_review_status: "pending" });
      await approve(review.id);
      expect((await compose(projectId)).json()).toEqual({ error: "render_already_composed", review_id: review.id });
      s = await state(projectId);
      expect(s.render_review_ready).toBe(true);
      // a newer export makes the approval stale; a rejected card can be re-composed
      const { renderId: second } = await exported(projectId, executor);
      expect((await state(projectId)).render_review_ready).toBe(false);
      const res2 = await compose(projectId);
      expect(res2.statusCode).toBe(201);
      await reject(res2.json().review_id as string);
      const res3 = await compose(projectId);
      expect(res3.statusCode, res3.body).toBe(201);
      expect(res3.json().review_id).not.toBe(res2.json().review_id);
      expect(((await gw.repos.getReview(res3.json().review_id as string))!.content as { render_id: string }).render_id).toBe(second);
      expect(renderRequests).toHaveLength(3);
    } finally {
      await executor.close();
    }
  });

  it("compose after Commit #2 uses the commit2 snapshot", async () => {
    const projectId = await chainToCommit2();
    const { executor } = await exported(projectId);
    try {
      const res = await compose(projectId);
      expect(res.statusCode, res.body).toBe(201);
      expect(((await gw.repos.getReview(res.json().review_id as string))!.content as { layout_snapshot: string }).layout_snapshot).toBe("commit2");
      expect(renderRequests[0]!.rooms).toHaveLength(2);
    } finally {
      await executor.close();
    }
  });

  it("compose failures: bridge 422 -> hard render_failure (deduped); unreachable/timeout -> soft; bad PNG -> bridge_bad_png", async () => {
    const projectId = await chainToCommit1();
    const { renderId, executor } = await exported(projectId);
    try {
      renderQueue.push({ status: 422, body: { error: "png_invalid", message: "section: not a PNG", raw_outputs: [] } });
      renderQueue.push({ status: 422, body: { error: "png_invalid", message: "section: not a PNG", raw_outputs: [] } });
      const first = await compose(projectId);
      expect(first.statusCode).toBe(422);
      expect(first.json()).toEqual({ error: "png_invalid", message: "section: not a PNG" });
      const second = await compose(projectId);
      expect(second.statusCode).toBe(422);
      const failures = await gw.repos.listReviewsOfKind(projectId, "render_failure");
      expect(failures).toHaveLength(1); // deduped per (job, error)
      expect(failures[0]!.status).toBe("pending"); // never auto-approved
      expect(failures[0]!.content).toMatchObject({ reason: "render_error", error: "png_invalid", hard: true, render_id: renderId });
      expect((await gw.repos.getRenderJob(renderId))!.status).toBe("exported"); // still composable
      expect((await events(projectId, "render_failed"))).toHaveLength(2);

      // transient: the bridge answers after the deadline -> aborted -> soft card
      setBridgeTimeouts({ renderMs: 60 });
      renderQueue.push({ status: 200, body: defaultRender, delayMs: 400 });
      const slow = await compose(projectId);
      expect(slow.statusCode).toBe(422);
      expect(slow.json().error).toBe("aidm_bridge_unreachable");
      const soft = (await gw.repos.listReviewsOfKind(projectId, "render_failure")).find(
        (r) => (r.content as { error: string }).error === "aidm_bridge_unreachable",
      )!;
      expect(soft.content).toMatchObject({ hard: false });
      setBridgeTimeouts({ ...BRIDGE_TIMEOUTS_DEFAULT });
      await sleep(450); // let the delayed stub response drain

      // the bridge returns something that is not a PNG
      renderQueue.push({ status: 200, body: (req: RenderReq) => {
        const r = defaultRender(req) as { control_maps: { lines_png_base64: string }[] };
        r.control_maps[1]!.lines_png_base64 = Buffer.from("not a png").toString("base64");
        return r;
      } });
      const bad = await compose(projectId);
      expect(bad.statusCode).toBe(422);
      expect(bad.json().error).toBe("bridge_bad_png");
      expect((await gw.repos.listReviewsOfKind(projectId, "render_failure")).some((r) => (r.content as { error: string }).error === "bridge_bad_png")).toBe(true);
      expect(await gw.repos.listReviewsOfKind(projectId, "render_review")).toHaveLength(0);
      // then a clean compose still works
      expect((await compose(projectId)).statusCode).toBe(201);
    } finally {
      await executor.close();
    }
  });

  // ---- finish-selection -------------------------------------------------------------

  it("finish-selection ladder: no review, not approved, stale, zod 400, bridge 422 / blocked / off-allowlist / empty -> no card", async () => {
    const projectId = await chainToCommit1();
    expect((await finishSelection(randomUUID(), SELECTION)).statusCode).toBe(404);
    const off = await gwOff.app.inject({ method: "POST", url: `/projects/${projectId}/finish-selection`, headers: svc, payload: SELECTION });
    expect(off.json().error).toBe("aidm_bridge_unavailable");
    expect((await finishSelection(projectId, SELECTION)).json()).toEqual({ error: "no_render_review" });
    const { renderId, executor } = await exported(projectId);
    try {
      const composed = await compose(projectId);
      expect((await finishSelection(projectId, SELECTION)).json()).toEqual({ error: "render_not_approved", status: "pending" });
      await approve(composed.json().review_id as string);
      // stale: a newer export
      await exported(projectId, executor);
      expect((await finishSelection(projectId, SELECTION)).json()).toEqual({ error: "render_review_stale", review_id: composed.json().review_id });
      const fresh = await compose(projectId);
      await approve(fresh.json().review_id as string);
      // stale: a newer confirmed brief
      const { review } = await gw.repos.createBriefWithReview(projectId, { meta: { brief_version: 2 } }, {}, false);
      await approve(review.id);
      expect((await finishSelection(projectId, SELECTION)).json().error).toBe("render_review_stale");
      // recover: export + compose against the new brief
      const { renderId: third } = await exported(projectId, executor);
      const again = await compose(projectId);
      await approve(again.json().review_id as string);
      expect(third).not.toBe(renderId);
      expect((await state(projectId)).render_review_ready).toBe(true);

      // zod bounds
      const bad = await finishSelection(projectId, { rooms: [], unexpected: 1 });
      expect(bad.statusCode).toBe(400);
      expect(bad.json().error).toBe("bad_request");
      const tooMany = await finishSelection(projectId, { doors: Array.from({ length: 121 }, (_, i) => ({ id: `D-${i}`, sku: DOOR_SKU })) });
      expect(tooMany.statusCode).toBe(400);
      expect(validateRequests).toHaveLength(0);

      // bridge verdicts: no card in any of these
      validateQueue.push({ status: 422, body: { error: "layout_invalid", message: "bad", raw_outputs: [] } });
      expect((await finishSelection(projectId, SELECTION)).json()).toEqual({ error: "layout_invalid", message: "bad" });
      validateQueue.push({ status: 200, body: { ops: [], review_items: [{ code: "unknown_sku", severity: "blocking", refs: ["D-001", "X"], message: "unknown sku X" }], blocking: ["unknown_sku"], diagnostics: { per_target: {}, counts: { blocking: 1 } } } });
      const blocked = await finishSelection(projectId, SELECTION);
      expect(blocked.statusCode).toBe(422);
      expect(blocked.json()).toEqual({ error: "finish_selection_blocked", blocking: ["unknown_sku"], items: [{ code: "unknown_sku", severity: "blocking", refs: ["D-001", "X"], message: "unknown sku X" }] });
      // the bridge emits an op the allowlist forbids: the gateway polices its own supplier
      validateQueue.push({ status: 200, body: { ops: [{ op: "set_parameter", args: { target_id: "D-001", param: "CHPT_Finish_Material", value: "x" } }], review_items: [], blocking: [], diagnostics: { per_target: {}, counts: {} } } });
      const off2 = await finishSelection(projectId, SELECTION);
      expect(off2.statusCode).toBe(422);
      expect(off2.json().error).toBe("param_not_allowlisted");
      expect(off2.json().detail).toMatchObject({ index: 0, reason: "param_not_allowlisted" });
      // a malformed op shape from the bridge is a contract error
      validateQueue.push({ status: 200, body: { ops: [{ op: "delete_element", args: { target_id: "D-001" } }], review_items: [], blocking: [], diagnostics: { per_target: {}, counts: {} } } });
      expect((await finishSelection(projectId, SELECTION)).json().error).toBe("finish_validate_error");
      // nothing selected -> nothing to commit
      validateQueue.push({ status: 200, body: { ops: [], review_items: [], blocking: [], diagnostics: { per_target: {}, counts: { ops: 0 } } } });
      expect((await finishSelection(projectId, { rooms: [] })).json().error).toBe("finish_selection_empty");
      expect(await gw.repos.listReviewsOfKind(projectId, "finish_commit")).toHaveLength(0);
      expect(await events(projectId, "finish_validate_failed")).toHaveLength(4); // 422, blocked, allowlist, contract
    } finally {
      await executor.close();
    }
  });

  it("finish-selection success: bridge request, finish_commit content, one pending at a time, actor token allowed", async () => {
    const projectId = await chainToCommit1();
    const { renderId, reviewId, executor } = await approvedRender(projectId);
    try {
      const res = await finishSelection(projectId, SELECTION, { ...actor });
      expect(res.statusCode, res.body).toBe(201);
      expect(res.json().status).toBe("pending");
      expect(res.json().counts).toMatchObject({ ops: 10, targets: 3 });
      const sent = validateRequests[0]!;
      expect(sent.project_id).toBe(projectId);
      expect(sent.id_map_ids).toEqual(["D-001", "W-001", "W-002"]);
      expect(sent.finish_tier).toBe("standard"); // brief without finish_tier -> default
      expect(sent.catalog_version).toBe(productsCatalog.catalog_version);
      expect(sent.render_ref).toBe(`mock-${renderId}-plan`);
      expect(sent.allow_placeholders).toBe(false);
      expect(sent.selection).toEqual({ ...SELECTION, casework: [], plumbing_fixtures: [], overrides: [] });
      expect((sent.layout as { meta: { phase: string } }).meta.phase).toBe("new"); // the frozen commit1 snapshot
      const review = (await gw.repos.getReview(res.json().review_id as string))!;
      const content = review.content as { ops: Op[]; selection: unknown; render_review_id: string; render_id: string; render_ref: string; render_blob_ref: string; catalog_version: string; finish_tier: string; brief_version: number };
      expect(content.ops).toHaveLength(10);
      expect(content.ops.every((o) => o.op === "set_parameter")).toBe(true);
      expect(content).toMatchObject({ render_review_id: reviewId, render_id: renderId, render_ref: `mock-${renderId}-plan`, catalog_version: productsCatalog.catalog_version, finish_tier: "standard", brief_version: 1 });
      expect(content.render_blob_ref).toMatch(/^[0-9a-f]{64}$/);
      // one pending finish_commit per project
      expect((await finishSelection(projectId, SELECTION)).json()).toEqual({ error: "finish_review_pending", review_id: review.id });
      await reject(review.id);
      const rebuilt = await finishSelection(projectId, SELECTION);
      expect(rebuilt.statusCode).toBe(201); // every rebuilt selection is a NEW card
      expect(rebuilt.json().review_id).not.toBe(review.id);
      // an APPROVED selection that can still be issued is never shadowed by a newer card
      await approve(rebuilt.json().review_id as string);
      expect((await finishSelection(projectId, SELECTION)).json()).toEqual({ error: "finish_review_awaiting_issue", review_id: rebuilt.json().review_id });
      await reject((await finishSelection(projectId, SELECTION)).json().review_id ?? rebuilt.json().review_id).catch(() => {});
      const s = await state(projectId);
      expect(s.finish).toMatchObject({ finish_review_id: rebuilt.json().review_id, status: "approved", envelope_status: null, reissues: 0, hard_failed: false });
      expect(s.finish_ready).toBe(true);
      expect(s.finish_done).toBe(false);
    } finally {
      await executor.close();
    }
  });

  // ---- issue-finish -----------------------------------------------------------------

  it("issue-finish sends the approved ops verbatim as Commit #3; commit -> finish_selections + finish_done; then everything says done", async () => {
    const projectId = await chainToCommit1();
    expect((await issueFinish(randomUUID())).statusCode).toBe(404);
    expect((await issueFinish(projectId)).json()).toEqual({ error: "no_finish_review" });
    const { executor } = await approvedRender(projectId);
    try {
      const sel = await finishSelection(projectId, SELECTION);
      expect((await issueFinish(projectId)).json()).toEqual({ error: "finish_review_not_approved", status: "pending" });
      await approve(sel.json().review_id as string);
      expect((await state(projectId)).finish_ready).toBe(true);
      const issued = await issueFinish(projectId);
      expect(issued.statusCode, issued.body).toBe(202);
      expect(issued.json().seq).toBe(4); // export took 3
      await waitFor(async () => (await state(projectId)).finish_done === true, "finish_done");
      const body = executor.delivered.at(-1)!;
      expect(body.commit_label).toBe(FINISH_LABEL);
      const review = (await gw.repos.getReview(sel.json().review_id as string))!;
      expect(body.approval_ref).toEqual({ review_id: review.id, content_hash: review.content_hash });
      expect(body.ops).toEqual((review.content as { ops: Op[] }).ops); // SI-2: verbatim
      const row = (await gw.repos.finishSelectionForProject(projectId))!;
      expect(row).toMatchObject({ review_id: review.id, envelope_id: issued.json().envelope_id, catalog_version: productsCatalog.catalog_version });
      expect(row.ops).toEqual((review.content as { ops: Op[] }).ops);
      expect(row.selection).toEqual({ ...SELECTION, casework: [], plumbing_fixtures: [], overrides: [] });
      expect((await events(projectId, "finish_done"))[0]).toMatchObject({ finish_review_id: review.id, seq: 4, ops: 10 });
      const s = await state(projectId);
      expect(s.finish_done).toBe(true);
      expect(s.finish_ready).toBe(false);
      expect(s.finish).toMatchObject({ status: "approved", envelope_status: "committed", reissues: 1 });
      expect(s.last_committed_seq).toBe(4);
      expect((await issueFinish(projectId)).json()).toEqual({ error: "finish_already_done" });
      expect((await finishSelection(projectId, SELECTION)).json()).toEqual({ error: "finish_already_done" });
    } finally {
      await executor.close();
    }
  });

  it("issue-finish rollbacks: hard -> finish_failure + finish_review_failed; transient -> re-issue with reissue_of, capped once", async () => {
    const projectId = await chainToCommit1();
    let mode: "hard" | "transient" | "commit" = "hard";
    const executor = await connectExecutor(projectId, async (body, defaults) => {
      if (!body.ops.some((o) => o.op === "set_parameter")) return defaults();
      if (mode === "commit") return defaults();
      return [
        { type: "ack", envelope_id: body.envelope_id, status: "accepted" },
        { type: "commit_result", envelope_id: body.envelope_id, status: "rolled_back", id_map_delta: [], errors: [
          mode === "hard"
            ? { op_index: 0, code: "unknown_param", message: "CHPT_Product_SKU not bound on Doors" }
            : { op_index: 0, code: "expired_ttl", message: "ttl" },
        ] },
      ];
    });
    try {
      await approvedRender(projectId, executor);
      const first = await finishSelection(projectId, SELECTION);
      await approve(first.json().review_id as string);
      const issued = await issueFinish(projectId);
      expect(issued.statusCode, issued.body).toBe(202);
      await waitFor(async () => (await gw.repos.finishHardFailure(projectId, first.json().review_id as string)) !== null, "hard failure");
      const failure = (await gw.repos.latestReviewOfKind(projectId, "finish_failure"))!;
      expect(failure.status).toBe("pending"); // never auto-approved
      expect(failure.content).toMatchObject({ reason: "executor_rejected", hard: true, finish_review_id: first.json().review_id, envelope_id: issued.json().envelope_id });
      expect((await issueFinish(projectId)).json()).toEqual({ error: "finish_review_failed", review_id: first.json().review_id });
      let s = await state(projectId);
      expect(s.finish).toMatchObject({ envelope_status: "rolled_back", hard_failed: true, reissues: 1 });
      expect(s.finish_ready).toBe(false);
      expect(s.finish_done).toBe(false);

      // a NEW selection restarts; transient rollbacks re-issue under the same review
      mode = "transient";
      const second = await finishSelection(projectId, SELECTION);
      expect(second.statusCode, second.body).toBe(201);
      await approve(second.json().review_id as string);
      const reviewId = second.json().review_id as string;
      for (let i = 1; i <= FINISH_REISSUE_CAP; i++) {
        const res = await issueFinish(projectId);
        expect(res.statusCode, res.body).toBe(202);
        expect(res.json().seq).toBe(4); // a rolled-back seq is reused (Phase 1–5 semantics)
        await waitFor(async () => (await gw.repos.latestEnvelopeForReview(reviewId))!.status === "rolled_back", `rollback ${i}`);
      }
      const issuedEvents = (await events(projectId, "envelope_issued")).filter((e) => e["seq"] === 4);
      expect(issuedEvents.filter((e) => e["reissue_of"]).length).toBe(FINISH_REISSUE_CAP - 1);
      expect((await state(projectId)).finish_ready).toBe(false); // the cap is visible before anyone asks to issue
      const capped = await issueFinish(projectId);
      expect(capped.json()).toEqual({ error: "finish_reissue_exhausted", reissues: FINISH_REISSUE_CAP });
      // the exhausted card is itself a hard finish_failure naming the review: spent
      expect((await issueFinish(projectId)).json()).toEqual({ error: "finish_review_failed", review_id: reviewId });
      const exhausted = (await gw.repos.listReviewsOfKind(projectId, "finish_failure")).filter(
        (r) => (r.content as { reason: string }).reason === "finish_reissue_exhausted",
      );
      expect(exhausted).toHaveLength(1); // filed once
      expect(exhausted[0]!.content).toMatchObject({ hard: true, finish_review_id: reviewId, reissues: FINISH_REISSUE_CAP });
      expect((await state(projectId)).finish_ready).toBe(false);

      // and a third selection can still complete
      mode = "commit";
      const third = await finishSelection(projectId, SELECTION);
      await approve(third.json().review_id as string);
      expect((await issueFinish(projectId)).statusCode).toBe(202);
      await waitFor(async () => (await state(projectId)).finish_done === true, "finish_done");
      s = await state(projectId);
      expect(s.recent_envelopes.filter((e: { status: string }) => e.status === "committed").map((e: { seq: number }) => e.seq).sort()).toEqual([1, 2, 3, 4]);
    } finally {
      await executor.close();
    }
  });

  // ---- SI-2 / SI-4 on the generic route --------------------------------------------

  it("POST /envelopes: model-writing ops are commit-class; a genuine approval_ref still cannot carry an off-allowlist param", async () => {
    const projectId = await chainToCommit1();
    for (const op of [
      { op: "set_parameter", args: { target_id: "W-001", param: "CHPT_Product_SKU", value: "x" } },
      { op: "set_phase_demolished", args: { target_id: "W-001" } },
      { op: "delete_element", args: { target_id: "W-001" } },
      { op: "update_wall", args: { target_id: "W-001", start: [0, 0], end: [1000, 0] } },
    ]) {
      const res = await inject({ method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc, payload: { ops: [op] } });
      expect(res.statusCode, op.op).toBe(422);
      expect(res.json().error).toBe("approval_ref_required");
    }
    // an approved review whose content ops include an off-category param (constructed
    // directly — finish-selection refuses to create one): the signer refuses to sign it
    const badOps = [{ op: "set_parameter", args: { target_id: "E-001", param: "CHPT_Finish_Material", value: "x" } }];
    const review = await gw.repos.createReview(projectId, "finish_commit", { ops: badOps }, true);
    const executor = await connectExecutor(projectId);
    try {
      const res = await inject({ method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc,
        payload: { ops: badOps, commit_label: "Commit #3 finishes", approval_ref: { review_id: review.id, content_hash: review.content_hash } } });
      expect(res.statusCode).toBe(422);
      expect(res.json().error).toBe("param_not_allowlisted");
      expect(executor.delivered).toHaveLength(0);
      // issue-finish on that review hits the same wall
      const viaRoute = await issueFinish(projectId);
      expect(viaRoute.statusCode).toBe(422);
      expect(viaRoute.json().error).toBe("param_not_allowlisted");
      // ops that differ from the approved content are refused before the signer
      const good = [{ op: "set_parameter", args: { target_id: "W-001", param: "CHPT_Product_SKU", value: "x" } }];
      const mismatch = await inject({ method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc,
        payload: { ops: good, approval_ref: { review_id: review.id, content_hash: review.content_hash } } });
      expect(mismatch.json().error).toBe("approval_ref_mismatch");
    } finally {
      await executor.close();
    }
  });

  // ---- review fixes: approval_ref on every op, compose guards, stale exports, lost frames ----

  it("POST /envelopes verifies EVERY approval_ref, not only on commit-class ops; branch-delta kinds are refused", async () => {
    const projectId = await chainToCommit1();
    const finish = await gw.repos.createReview(projectId, "finish_commit", { ops: [{ op: "set_parameter", args: { target_id: "W-001", param: "CHPT_Product_SKU", value: "x" } }] }, true);
    const executor = await connectExecutor(projectId);
    try {
      // a non-commit-class op carrying an approved finish_commit ref: the ops differ -> refused
      // (before the fix it was signed, committed, and recordCommitResult wrote finish_selections)
      const res = await inject({ method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc,
        payload: { ops: [{ op: "create_level", args: { name: "Level 9", elevation: 3000 } }], approval_ref: { review_id: finish.id, content_hash: finish.content_hash } } });
      expect(res.statusCode).toBe(422);
      expect(res.json().error).toBe("approval_ref_mismatch");
      expect(await gw.repos.finishSelectionForProject(projectId)).toBeNull();
      // an approved branch delta (interior_plan) can never back an envelope directly
      const interior = await gw.repos.createReview(projectId, "interior_plan", { ops: INTERIOR_OPS, layout: {}, brief_version: 1 }, true);
      const branch = await inject({ method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc,
        payload: { ops: INTERIOR_OPS, approval_ref: { review_id: interior.id, content_hash: interior.content_hash } } });
      expect(branch.statusCode).toBe(422);
      expect(branch.json().error).toBe("approval_ref_kind");
      expect(executor.delivered).toHaveLength(0);
    } finally {
      await executor.close();
    }
  });

  it("compose guards: one pending render_review per project (index), a card for the export blocks any job status", async () => {
    const projectId = await chainToCommit1();
    const { renderId, executor } = await exported(projectId);
    try {
      // a pending render_review already exists for another export -> the open card decides first
      // (the ladder refuses before the bridge is paid; the unique index is the backstop)
      const other = await gw.repos.createReview(projectId, "render_review", { render_id: randomUUID(), brief_version: 1 }, false);
      const res = await compose(projectId);
      expect(res.statusCode).toBe(409);
      expect(res.json()).toEqual({ error: "render_review_pending", review_id: other.id });
      expect((await gw.repos.getRenderJob(renderId))!.status).toBe("exported"); // not flipped
      await expect(
        gw.repos.createReview(projectId, "render_review", { render_id: renderId, brief_version: 1 }, false),
      ).rejects.toThrow(/reviews_one_pending_render_review/);
      // a card for THIS export exists while the job still says exported (crash between insert and flip)
      await gw.pool.query("DELETE FROM reviews WHERE project_id = $1 AND kind = 'render_review'", [projectId]);
      const pending = await gw.repos.createReview(projectId, "render_review", { render_id: renderId, brief_version: 1 }, false);
      expect((await compose(projectId)).json()).toEqual({ error: "render_review_pending", review_id: pending.id });
      await approve(pending.id);
      expect((await compose(projectId)).json()).toEqual({ error: "render_already_composed", review_id: pending.id });
      expect(renderRequests).toHaveLength(0);
    } finally {
      await executor.close();
    }
  });

  it("a Commit #2 after the export makes it stale (re-export); the review pins the frozen layout it was about", async () => {
    const projectId = await chainToCommit1();
    const executor = await connectExecutor(projectId);
    try {
      const { renderId } = await exported(projectId, executor);
      // Commit #2 lands after the export (seq 4 > export seq 3)
      const furnish = await inject({ method: "POST", url: `/projects/${projectId}/furnish-layout`, headers: svc });
      await approve(furnish.json().review_id as string);
      const mep = await inject({ method: "POST", url: `/projects/${projectId}/plan-mep`, headers: svc, payload: { confirmations: { panel: [50, 3000], slab_to_slab_mm: 3000 } } });
      await approve(mep.json().review_id as string);
      const merge = await inject({ method: "POST", url: `/projects/${projectId}/merge-commit2`, headers: svc });
      expect(merge.statusCode, merge.body).toBe(201);
      await approve(merge.json().review_id as string);
      await commitEnvelope(await issueFor(projectId, merge.json().review_id as string, 4, "Commit #2"));
      const stale = await compose(projectId);
      expect(stale.statusCode).toBe(409);
      expect(stale.json()).toMatchObject({ error: "render_export_stale", render_id: renderId, export_seq: 3, commit2_seq: 4 });
      // re-export -> the card is about commit2
      await exported(projectId, executor);
      const res = await compose(projectId);
      expect(res.statusCode, res.body).toBe(201);
      expect(((await gw.repos.getReview(res.json().review_id as string))!.content as { layout_snapshot: string }).layout_snapshot).toBe("commit2");
    } finally {
      await executor.close();
    }
  });

  it("a review approved against commit1 goes stale when Commit #2 lands: render_review_ready false, finish-selection refused", async () => {
    const projectId = await chainToCommit1();
    const { executor } = await approvedRender(projectId);
    try {
      expect((await state(projectId)).render_review_ready).toBe(true);
      const furnish = await inject({ method: "POST", url: `/projects/${projectId}/furnish-layout`, headers: svc });
      await approve(furnish.json().review_id as string);
      const mep = await inject({ method: "POST", url: `/projects/${projectId}/plan-mep`, headers: svc, payload: { confirmations: { panel: [50, 3000], slab_to_slab_mm: 3000 } } });
      await approve(mep.json().review_id as string);
      const merge = await inject({ method: "POST", url: `/projects/${projectId}/merge-commit2`, headers: svc });
      await approve(merge.json().review_id as string);
      await commitEnvelope(await issueFor(projectId, merge.json().review_id as string, 4, "Commit #2"));
      expect((await state(projectId)).render_review_ready).toBe(false);
      expect((await finishSelection(projectId, SELECTION)).json().error).toBe("render_review_stale");
      expect(validateRequests).toHaveLength(0);
    } finally {
      await executor.close();
    }
  });

  it("frames that never arrive: a newer committed envelope fails the stranded job instead of feeding it a stranger's frame", async () => {
    const projectId = await chainToCommit1();
    const silent = await connectExecutor(projectId, async (body) => [
      { type: "ack", envelope_id: body.envelope_id, status: "accepted" },
      { type: "commit_result", envelope_id: body.envelope_id, status: "committed", id_map_delta: [], errors: [] },
    ]);
    try {
      const res = await renderViews(projectId);
      expect(res.statusCode, res.body).toBe(202);
      const renderId = res.json().render_id as string;
      await waitFor(async () => (await state(projectId)).render?.envelope_status === "committed", "export committed");
      expect((await gw.repos.getRenderJob(renderId))!.status).toBe("exporting");
      expect((await compose(projectId)).json()).toMatchObject({ error: "render_export_in_progress", attached: 0 });
      // another envelope commits: the stranded job can never complete -> terminal
      const other = await inject({ method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc,
        payload: { ops: [{ op: "create_level", args: { name: "Level 9", elevation: 3000 } }] } });
      expect(other.statusCode, other.body).toBe(202);
      await waitFor(async () => (await gw.repos.getRenderJob(renderId))!.status === "failed", "stranded job failed");
      expect((await events(projectId, "render_export_failed")).at(-1)).toMatchObject({ render_id: renderId, cause: "frames_lost" });
      // a late frame now finds no exporting job
      silent.send({ type: "export_ready", kind: "view", blob_ref: sha256(pngVariant(3)) });
      await waitFor(async () => (await events(projectId, "export_ready_unmatched")).length === 1, "late frame unmatched");
      expect((await compose(projectId)).json()).toEqual({ error: "render_export_failed", render_id: renderId });
    } finally {
      await silent.close();
    }
  });

  // ---- blobs -------------------------------------------------------------------------

  it("blob PUT/GET matrix: workstation-only PUT with hash verification, actor/service GET, 503 when unset", async () => {
    const projectId = await chainToCommit1();
    const other = await createProject();
    const token = (await inject({ method: "POST", url: `/projects/${projectId}/workstations`, headers: svc, payload: { workstation_id: "ws-up-01" } })).json().token as string;
    const otherToken = (await inject({ method: "POST", url: `/projects/${other}/workstations`, headers: svc, payload: { workstation_id: "ws-up-02" } })).json().token as string;
    const bytes = pngVariant(555);
    const ref = sha256(bytes);
    const put = (r: string, body: Buffer | string, headers: Record<string, string>, contentType = "image/png") =>
      inject({ method: "PUT", url: `/projects/${projectId}/blobs/${r}`, headers: { ...headers, "content-type": contentType }, payload: body });
    const ws = { authorization: `Bearer ${token}` };
    expect((await put(ref, bytes, {})).statusCode).toBe(401);
    expect((await put(ref, bytes, svc)).statusCode).toBe(403); // the service token is not a workstation
    expect((await put(ref, bytes, { authorization: `Bearer ${otherToken}` })).statusCode).toBe(403); // another project's workstation
    expect((await put("not-a-ref", bytes, ws)).json()).toEqual({ error: "bad_blob_ref" });
    expect((await put(ref, Buffer.from("plain text"), ws, "application/octet-stream")).statusCode).toBe(415);
    expect((await put(ref, "text", ws, "text/plain")).statusCode).toBe(415); // no parser for that type
    const wrong = await put(sha256(Buffer.from("other")), bytes, ws);
    expect(wrong.statusCode).toBe(422);
    expect(wrong.json()).toMatchObject({ error: "blob_hash_mismatch", detail: { actual: ref } });
    const created = await put(ref, bytes, ws);
    expect(created.statusCode).toBe(201);
    expect(created.json()).toEqual({ blob_ref: ref, bytes: bytes.length, type: "png", created: true });
    const repeat = await put(ref, bytes, ws);
    expect(repeat.statusCode).toBe(200);
    expect(repeat.json().created).toBe(false);
    expect(await events(projectId, "blob_stored")).toHaveLength(1);
    const doc = Buffer.from('{"parameters": []}');
    const putJson = await put(sha256(doc), doc, ws, "application/octet-stream");
    expect(putJson.statusCode).toBe(201);
    expect(putJson.json().type).toBe("json");
    // GET: actor (header or query), service; content type from the bytes
    const get = (r: string, headers: Record<string, string> = {}, query = "") =>
      inject({ method: "GET", url: `/projects/${projectId}/blobs/${r}${query}`, headers });
    expect((await get(ref)).statusCode).toBe(401);
    expect((await get(ref, ws)).statusCode).toBe(403); // a workstation token cannot read
    const asActor = await get(ref, {}, `?actor_token=${ACTOR}`);
    expect(asActor.statusCode).toBe(200);
    expect(asActor.headers["content-type"]).toBe("image/png");
    expect(asActor.headers["cache-control"]).toContain("immutable");
    expect(asActor.rawPayload.equals(bytes)).toBe(true);
    expect((await get(sha256(doc), svc)).headers["content-type"]).toBe("application/json");
    expect((await get(sha256(Buffer.from("missing")), svc)).json()).toEqual({ error: "unknown_blob" });
    expect((await get("zz", svc)).json()).toEqual({ error: "bad_blob_ref" });
    expect((await inject({ method: "GET", url: `/projects/${randomUUID()}/blobs/${ref}`, headers: svc })).statusCode).toBe(404);
    const off = await gwOff.app.inject({ method: "GET", url: `/projects/${projectId}/blobs/${ref}`, headers: svc });
    expect(off.statusCode).toBe(503);
    expect(off.json().error).toBe("blob_store_unavailable");
    const offPut = await gwOff.app.inject({ method: "PUT", url: `/projects/${projectId}/blobs/${ref}`, headers: { ...ws, "content-type": "image/png" }, payload: bytes });
    expect(offPut.statusCode).toBe(503);
  });

  // ---- UI ----------------------------------------------------------------------------

  it("review cards: render_review shows blob URLs, the escaped hostile tag and PLACEHOLDER badges; finish_commit shows the selection", async () => {
    const projectId = await chainToCommit1();
    const { reviewId, executor } = await approvedRender(projectId);
    try {
      const sel = await finishSelection(projectId, SELECTION);
      expect(sel.statusCode).toBe(201);
      const page = await inject({ method: "GET", url: `/ui/projects/${projectId}/reviews?actor_token=${ACTOR}` });
      expect(page.statusCode).toBe(200);
      const html = page.body;
      const content = (await gw.repos.getReview(reviewId))!.content as { control_maps: { canny_ref: string }[]; renders: { blob_ref: string }[] };
      expect(html).toContain(`/projects/${projectId}/blobs/${content.control_maps[0]!.canny_ref}?actor_token=${ACTOR}`);
      expect(html).toContain(`/projects/${projectId}/blobs/${content.renders[0]!.blob_ref}?actor_token=${ACTOR}`);
      expect(html).not.toContain(HOSTILE_TAG);
      expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
      expect(html).toContain("PLACEHOLDER</span>");
      expect(html).toContain("CHPT_Product_SKU: 3");
      expect(html).toContain("finish tier <strong>standard</strong>");
      expect(html).toContain("<td>wall</td><td><code>R-001</code></td>");
      expect(html).toContain("<td>door</td><td><code>D-001</code></td>");
    } finally {
      await executor.close();
    }
  });
});
