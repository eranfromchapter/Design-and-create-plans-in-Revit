// DB-backed integration tests: REST auth (SI-10), enrollment, envelope lifecycle,
// reviews + drift gate, WSS hello/auth_ok/one-executor, and a scripted fake executor
// driving ack/commit_result. Requires DATABASE_URL (CI: postgres service container;
// local: `make dev-up`).
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import type { InjectOptions } from "fastify";
import WebSocket from "ws";
import { idMapHash } from "@chapter/contracts";
import { loadConfig, type Config } from "../src/config.js";
import { buildGateway, type Gateway } from "../src/app.js";

const DATABASE_URL = process.env["DATABASE_URL"];

const SERVICE = "service-token-0123456789";
const ACTOR = "actor-token-eran";

const WALL_OPS = [1, 2, 3, 4].map((i) => ({
  op: "create_wall",
  args: {
    id: `W-00${i}`,
    start: [0, (i - 1) * 100],
    end: [4000, (i - 1) * 100],
    revit_type: "CHPT_Partition_92mm_PLACEHOLDER",
    height: 2700,
    phase: "new",
  },
}));

describe.skipIf(!DATABASE_URL)("gateway (DB-backed)", () => {
  let gw: Gateway;
  let config: Config;
  let baseUrl: string;
  let port: number;

  beforeAll(async () => {
    config = loadConfig({
      DATABASE_URL: DATABASE_URL!,
      ENVELOPE_MASTER_KEY: "07".repeat(32),
      SERVICE_TOKEN: SERVICE,
      ACTOR_TOKENS: `${ACTOR}:eran@hellochapter.com`,
      PORT: "0",
    });
    gw = await buildGateway(config, { logger: false });
    baseUrl = await gw.app.listen({ port: 0, host: "127.0.0.1" });
    port = Number(new URL(baseUrl).port);
  });

  afterAll(async () => {
    await gw.app.close();
    await gw.pool.end();
  });

  beforeEach(async () => {
    await gw.pool.query(
      "TRUNCATE reviews, id_map, event_log, envelopes, workstations, projects",
    );
  });

  const inject = (opts: InjectOptions) => gw.app.inject(opts);
  const svc = { authorization: `Bearer ${SERVICE}` };
  const actor = { authorization: `Bearer ${ACTOR}` };

  async function createProjectAndWorkstation(): Promise<{ projectId: string; token: string; publicKey: string }> {
    const p = await inject({ method: "POST", url: "/projects", headers: svc, payload: { name: "Test" } });
    expect(p.statusCode).toBe(201);
    const { id, signing_public_key } = p.json();
    const w = await inject({
      method: "POST",
      url: `/projects/${id}/workstations`,
      headers: svc,
      payload: { workstation_id: "ws-design-01" },
    });
    expect(w.statusCode).toBe(201);
    return { projectId: id, token: w.json().token, publicKey: signing_public_key };
  }

  function connectExecutor(token: string, hello: object): Promise<{ ws: WebSocket; authOk: Record<string, unknown> }> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`ws://127.0.0.1:${port}/wss`, {
        headers: { authorization: `Bearer ${token}` },
      });
      ws.once("open", () => ws.send(JSON.stringify(hello)));
      ws.once("message", (data) => resolve({ ws, authOk: JSON.parse(data.toString()) }));
      ws.once("error", reject);
      ws.once("unexpected-response", (_req, res) => reject(new Error(`upgrade ${res.statusCode}`)));
    });
  }

  const EMPTY_HASH = idMapHash({});
  const helloMsg = {
    type: "hello",
    workstation_id: "ws-design-01",
    plugin_version: "0.1.0",
    last_committed_seq: 0,
    id_map_hash: EMPTY_HASH,
  };

  describe("SI-10 auth", () => {
    it("unauthenticated → 401, wrong token → 403, and nothing is signed", async () => {
      const { projectId } = await createProjectAndWorkstation();
      const noAuth = await inject({ method: "POST", url: `/projects/${projectId}/envelopes`, payload: { ops: WALL_OPS } });
      expect(noAuth.statusCode).toBe(401);
      const badAuth = await inject({
        method: "POST",
        url: `/projects/${projectId}/envelopes`,
        headers: { authorization: "Bearer wrong-token-000000000" },
        payload: { ops: WALL_OPS },
      });
      expect(badAuth.statusCode).toBe(403);
      const rows = await gw.pool.query("SELECT count(*)::int AS n FROM envelopes");
      expect(rows.rows[0].n).toBe(0);
    });

    it("actor tokens cannot use service endpoints and vice versa", async () => {
      const asActor = await inject({ method: "POST", url: "/projects", headers: actor, payload: { name: "x" } });
      expect(asActor.statusCode).toBe(403);
      const { projectId } = await createProjectAndWorkstation();
      await gw.repos.createReview(projectId, "drift", { note: "t" }, false);
      const reviews = await gw.repos.listReviews(projectId);
      const asService = await inject({ method: "POST", url: `/reviews/${reviews[0]!.id}/approve`, headers: svc, payload: {} });
      expect(asService.statusCode).toBe(403);
    });
  });

  describe("WSS session", () => {
    it("hello → auth_ok delivers the project public key; second executor refused", async () => {
      const { projectId, token, publicKey } = await createProjectAndWorkstation();
      const { ws, authOk } = await connectExecutor(token, helloMsg);
      expect(authOk).toEqual({ type: "auth_ok", project_id: projectId, signing_public_key: publicKey });

      await expect(connectExecutor(token, helloMsg)).rejects.toThrow(/upgrade 409/);
      ws.close();
      await new Promise((r) => setTimeout(r, 50));
    });

    it("bad workstation token → upgrade 401", async () => {
      await createProjectAndWorkstation();
      await expect(connectExecutor("not-a-token", helloMsg)).rejects.toThrow(/upgrade 401/);
    });

    it("hello with mismatched seq/hash marks drift and creates a pending review", async () => {
      const { projectId, token } = await createProjectAndWorkstation();
      const { ws } = await connectExecutor(token, { ...helloMsg, last_committed_seq: 7 });
      await new Promise((r) => setTimeout(r, 100));
      const project = await gw.repos.getProject(projectId);
      expect(project?.drift_state).toBe("dirty");
      expect(await gw.repos.pendingReviewCount(projectId)).toBe(1);
      ws.close();
    });
  });

  describe("envelope lifecycle", () => {
    it("no executor connected → 409", async () => {
      const { projectId } = await createProjectAndWorkstation();
      const res = await inject({
        method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc, payload: { ops: WALL_OPS },
      });
      expect(res.statusCode).toBe(409);
      expect(res.json().error).toBe("no_executor_connected");
    });

    it("full loop: POST → WSS delivery → ack → commit_result → id_map + state", async () => {
      const { projectId, token } = await createProjectAndWorkstation();
      const { ws } = await connectExecutor(token, helloMsg);

      const delivered = new Promise<{ payload: string; sig: string }>((resolve) => {
        ws.on("message", (data) => {
          const msg = JSON.parse(data.toString());
          if (msg.type === "envelope") resolve(msg);
        });
      });

      const res = await inject({
        method: "POST",
        url: `/projects/${projectId}/envelopes`,
        headers: svc,
        payload: { ops: WALL_OPS, commit_label: "test walls" },
      });
      expect(res.statusCode).toBe(202);
      const { envelope_id, seq } = res.json();
      expect(seq).toBe(1);

      const wire = await delivered;
      const body = JSON.parse(wire.payload);
      expect(body.envelope_id).toBe(envelope_id);
      expect(body.workstation_id).toBe("ws-design-01");

      // a second POST while this one is in flight → 409 (partial unique index)
      ws.send(JSON.stringify({ type: "ack", envelope_id, status: "accepted" }));
      await new Promise((r) => setTimeout(r, 100));
      const inFlight = await inject({
        method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc, payload: { ops: WALL_OPS },
      });
      expect(inFlight.statusCode).toBe(409);
      expect(inFlight.json().error).toBe("envelope_in_flight");

      ws.send(JSON.stringify({
        type: "commit_result",
        envelope_id,
        status: "committed",
        id_map_delta: [
          { logical_id: "W-001", element_id: 1000001 },
          { logical_id: "W-002", element_id: 1000002 },
          { logical_id: "W-003", element_id: 1000003 },
          { logical_id: "W-004", element_id: 1000004 },
        ],
        errors: [],
      }));
      await new Promise((r) => setTimeout(r, 150));

      const state = await inject({ method: "GET", url: `/projects/${projectId}/state`, headers: svc });
      const s = state.json();
      expect(s.last_committed_seq).toBe(1);
      expect(Object.keys(s.id_map)).toHaveLength(4);
      expect(s.id_map_hash).toBe(
        idMapHash({ "W-001": 1000001, "W-002": 1000002, "W-003": 1000003, "W-004": 1000004 }),
      );
      expect(s.recent_envelopes[0].status).toBe("committed");
      ws.close();
    });

    it("schema-invalid args → 422, never signed", async () => {
      const { projectId, token } = await createProjectAndWorkstation();
      const { ws } = await connectExecutor(token, helloMsg);
      const res = await inject({
        method: "POST",
        url: `/projects/${projectId}/envelopes`,
        headers: svc,
        payload: { ops: [{ op: "create_level", args: { name: "L1" } }] },
      });
      expect(res.statusCode).toBe(422);
      expect(res.json().detail.reason).toBe("invalid_args");
      const rows = await gw.pool.query("SELECT count(*)::int AS n FROM envelopes");
      expect(rows.rows[0].n).toBe(0);
      ws.close();
    });

    it("expireStaleEnvelopes flips overdue issued envelopes", async () => {
      const { projectId } = await createProjectAndWorkstation();
      await gw.repos.insertIssuedEnvelope({
        envelopeId: "0b5e7a1c-2d3f-4a5b-8c9d-0e1f2a3b4c00",
        projectId,
        workstationId: "ws-design-01",
        seq: 1,
        payload: JSON.stringify({ ttl_s: 10 }),
        sig: "0".repeat(128),
        issuedAt: new Date(Date.now() - 60_000).toISOString(),
      });
      expect(await gw.repos.expireStaleEnvelopes()).toBe(1);
    });
  });

  describe("drift gate + reviews", () => {
    it("dirty project → envelope POST 409; approving the drift review clears it", async () => {
      const { projectId, token } = await createProjectAndWorkstation();
      const { ws } = await connectExecutor(token, helloMsg);

      // executor reports divergence (the production signal from DocumentChangedWatcher)
      ws.send(JSON.stringify({
        type: "state_divergence", last_valid_seq: 0, id_map_hash: EMPTY_HASH, detail: "manual undo",
      }));
      await new Promise((r) => setTimeout(r, 100));

      const blocked = await inject({
        method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc, payload: { ops: WALL_OPS },
      });
      expect(blocked.statusCode).toBe(409);
      expect(blocked.json().error).toBe("drift_review_pending");

      const list = await inject({ method: "GET", url: `/projects/${projectId}/reviews`, headers: actor });
      const review = list.json().reviews.find((r: { kind: string }) => r.kind === "drift");
      const approve = await inject({ method: "POST", url: `/reviews/${review.id}/approve`, headers: actor, payload: {} });
      expect(approve.statusCode).toBe(200);
      expect(approve.json().decided_by).toBe("eran@hellochapter.com");

      const after = await inject({
        method: "POST", url: `/projects/${projectId}/envelopes`, headers: svc, payload: { ops: WALL_OPS },
      });
      expect(after.statusCode).toBe(202); // gate cleared; executor still connected
      ws.close();
    });

    it("deciding a review twice → 409; unknown review → 404", async () => {
      const { projectId } = await createProjectAndWorkstation();
      const review = await gw.repos.createReview(projectId, "drift", { x: 1 }, false);
      await inject({ method: "POST", url: `/reviews/${review.id}/reject`, headers: actor, payload: {} });
      const again = await inject({ method: "POST", url: `/reviews/${review.id}/approve`, headers: actor, payload: {} });
      expect(again.statusCode).toBe(409);
      const missing = await inject({
        method: "POST", url: "/reviews/0b5e7a1c-2d3f-4a5b-8c9d-0e1f2a3b4c99/approve", headers: actor, payload: {},
      });
      expect(missing.statusCode).toBe(404);
    });

    it("review page renders (escaped) and requires an actor token", async () => {
      const { projectId } = await createProjectAndWorkstation();
      await gw.repos.createReview(projectId, "drift", { note: "<script>alert(1)</script>" }, false);
      const denied = await inject({ method: "GET", url: `/ui/projects/${projectId}/reviews` });
      expect(denied.statusCode).toBe(401);
      const page = await inject({
        method: "GET",
        url: `/ui/projects/${projectId}/reviews?actor_token=${ACTOR}`,
      });
      expect(page.statusCode).toBe(200);
      expect(page.body).toContain("&lt;script&gt;");
      expect(page.body).not.toContain("<script>alert");
      expect(page.body).toContain("Approve");
    });
  });
});
