// DB-backed Phase 3 briefs flow: transcripts upload -> versioned brief + pending
// client_brief review -> approve confirms the brief (row + content.meta) -> the
// next upload passes the prior brief and becomes v2. The extractor is a local
// stub speaking the real /extract contract and RECORDING request bodies, so the
// version/prior chaining is what's tested. Requires DATABASE_URL.
import { createServer, type Server } from "node:http";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { loadConfig, type Config } from "../src/config.js";
import { buildGateway, type Gateway } from "../src/app.js";

const DATABASE_URL = process.env["DATABASE_URL"];
const SERVICE = "service-token-0123456789";
const ACTOR = "actor-token-eran";

function briefFor(projectId: string, version: number): Record<string, unknown> {
  return {
    meta: { project_id: projectId, brief_version: version, source_sessions: [`s${version}`] },
    rooms_required: [{ program: "bedroom", count: 2 + version, confidence: 1.0 }],
    adjacency_rules: [],
    style_tags: ["modern"],
    ...(version > 1
      ? {
          contradictions: [
            {
              field: "rooms_required.bedroom",
              earlier: `count=${1 + version}`,
              later: `count=${2 + version}`,
              resolution: "latest_wins",
            },
          ],
        }
      : {}),
  };
}

type Canned = { status: number; body?: unknown };
const cannedQueue: Canned[] = [];
const seenRequests: Record<string, unknown>[] = [];
let extractor: Server;
let extractorUrl: string;

describe.skipIf(!DATABASE_URL)("gateway briefs flow (DB-backed)", () => {
  let gw: Gateway;
  let config: Config;

  beforeAll(async () => {
    extractor = createServer((req, res) => {
      let raw = "";
      req.on("data", (c) => (raw += c));
      req.on("end", () => {
        const parsed = JSON.parse(raw) as Record<string, unknown>;
        seenRequests.push(parsed);
        const canned = cannedQueue.shift();
        if (canned) {
          res.writeHead(canned.status, { "content-type": "application/json" });
          res.end(JSON.stringify(canned.body));
          return;
        }
        const body = {
          brief: briefFor(parsed["project_id"] as string, parsed["brief_version"] as number),
          diagnostics: {
            per_session: [],
            injection_hits: 0,
            notes: [],
            contradiction_count: (parsed["brief_version"] as number) > 1 ? 1 : 0,
          },
        };
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify(body));
      });
    });
    await new Promise<void>((resolve) => extractor.listen(0, "127.0.0.1", resolve));
    const address = extractor.address();
    if (typeof address === "string" || !address) throw new Error("no extractor port");
    extractorUrl = `http://127.0.0.1:${address.port}`;

    config = loadConfig({
      DATABASE_URL: DATABASE_URL!,
      ENVELOPE_MASTER_KEY: "07".repeat(32),
      SERVICE_TOKEN: SERVICE,
      ACTOR_TOKENS: `${ACTOR}:eran@hellochapter.com`,
      PORT: "0",
      BRIEF_EXTRACTOR_URL: extractorUrl,
    });
    gw = await buildGateway(config, { logger: false });
    await gw.app.ready();
  });

  afterAll(async () => {
    await gw.app.close();
    await gw.pool.end();
    await new Promise((resolve) => extractor.close(resolve));
  });

  beforeEach(async () => {
    cannedQueue.length = 0;
    seenRequests.length = 0;
    await gw.pool.query(
      "TRUNCATE briefs, reviews, id_map, event_log, envelopes, workstations, projects",
    );
  });

  const svc = { authorization: `Bearer ${SERVICE}` };
  const actor = { authorization: `Bearer ${ACTOR}` };

  async function createProject(): Promise<string> {
    const res = await gw.app.inject({
      method: "POST", url: "/projects", headers: svc, payload: { name: "briefs-flow" },
    });
    return res.json().id as string;
  }

  async function upload(projectId: string) {
    return gw.app.inject({
      method: "POST",
      url: `/projects/${projectId}/transcripts`,
      headers: svc,
      payload: { sessions: [{ session_id: "s1", text: "CLIENT: three bedrooms" }] },
    });
  }

  it("upload stores brief v1 with a pending client_brief review", async () => {
    const projectId = await createProject();
    const res = await upload(projectId);
    expect(res.statusCode).toBe(201);
    const { brief_version, status, review_id } = res.json();
    expect(brief_version).toBe(1);
    expect(status).toBe("pending");

    const review = await gw.repos.getReview(review_id as string);
    expect(review?.kind).toBe("client_brief");

    const stored = await gw.app.inject({
      method: "GET", url: `/projects/${projectId}/brief`, headers: svc,
    });
    expect(stored.statusCode).toBe(200);
    expect(stored.json().confirmed_by_client).toBe(false);
    expect(stored.json().brief.meta.confirmed_by_client).toBeUndefined();
  });

  it("approving the review confirms the brief on the row AND in content.meta", async () => {
    const projectId = await createProject();
    const reviewId = (await upload(projectId)).json().review_id as string;
    const approved = await gw.app.inject({
      method: "POST", url: `/reviews/${reviewId}/approve`, headers: actor, payload: {},
    });
    expect(approved.statusCode).toBe(200);

    const stored = await gw.app.inject({
      method: "GET", url: `/projects/${projectId}/brief`, headers: svc,
    });
    expect(stored.json().confirmed_by_client).toBe(true);
    expect(stored.json().brief.meta.confirmed_by_client).toBe(true);
  });

  it("second upload passes the prior brief and becomes v2", async () => {
    const projectId = await createProject();
    await upload(projectId);
    const res = await upload(projectId);
    expect(res.json().brief_version).toBe(2);
    expect(res.json().contradiction_count).toBe(1);

    expect(seenRequests).toHaveLength(2);
    expect(seenRequests[0]!["brief_version"]).toBe(1);
    expect(seenRequests[0]!["prior_brief"]).toBeUndefined();
    expect(seenRequests[1]!["brief_version"]).toBe(2);
    expect((seenRequests[1]!["prior_brief"] as { meta: { brief_version: number } }).meta.brief_version).toBe(1);
  });

  it("extractor 422 passes through and preserves raw outputs in the event log", async () => {
    const projectId = await createProject();
    cannedQueue.push({
      status: 422,
      body: {
        error: "extraction_invalid",
        message: "failed after one repair retry",
        raw_outputs: [{ rooms_required: "three" }],
      },
    });
    const res = await upload(projectId);
    expect(res.statusCode).toBe(422);
    expect(res.json().error).toBe("extraction_invalid");

    const logged = await gw.pool.query(
      "SELECT payload FROM event_log WHERE project_id = $1 AND kind = 'brief_extraction_failed'",
      [projectId],
    );
    expect(logged.rowCount).toBe(1);
    expect(logged.rows[0].payload.raw_outputs).toEqual([{ rooms_required: "three" }]);
  });

  it("transcripts without an extractor configured is 503; empty project has no brief", async () => {
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
        method: "POST", url: "/projects", headers: svc, payload: { name: "no-extractor" },
      })).json().id as string;
      const res = await bare.app.inject({
        method: "POST",
        url: `/projects/${projectId}/transcripts`,
        headers: svc,
        payload: { sessions: [{ session_id: "s1", text: "hello" }] },
      });
      expect(res.statusCode).toBe(503);
      const none = await bare.app.inject({
        method: "GET", url: `/projects/${projectId}/brief`, headers: svc,
      });
      expect(none.statusCode).toBe(404);
      expect(none.json().error).toBe("no_brief");
    } finally {
      await bare.app.close();
      await bare.pool.end();
    }
  });
});
