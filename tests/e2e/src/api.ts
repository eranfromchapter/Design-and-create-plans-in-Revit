// Typed REST client for the gateway (zod-parsed responses at the boundary).
import { z } from "zod";
import { ACTOR_TOKEN, SERVICE_TOKEN } from "./harness.js";

const created = z.object({ id: z.string(), signing_public_key: z.string() });
const enrolled = z.object({ workstation_id: z.string(), token: z.string() });
const issued = z.object({ envelope_id: z.string(), seq: z.number() });
const stateSchema = z.object({
  drift_state: z.enum(["clean", "dirty"]),
  commit0_done: z.boolean(),
  executor_connected: z.boolean(),
  last_committed_seq: z.number(),
  id_map: z.record(z.string(), z.number()),
  id_map_hash: z.string(),
  pending_reviews: z.number(),
  recent_envelopes: z.array(
    z.object({
      envelope_id: z.string(),
      seq: z.number(),
      status: z.string(),
      reject_reason: z.string().nullable(),
    }),
  ),
});
const reviews = z.object({
  reviews: z.array(z.object({ id: z.string(), kind: z.string(), status: z.string() })),
});

export class GatewayApi {
  constructor(private readonly baseUrl: string) {}

  private async request(
    method: string,
    path: string,
    token: string | null,
    body?: unknown,
  ): Promise<{ status: number; json: unknown }> {
    const res = await fetch(this.baseUrl + path, {
      method,
      headers: {
        ...(token ? { authorization: `Bearer ${token}` } : {}),
        ...(body !== undefined ? { "content-type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return { status: res.status, json: await res.json().catch(() => null) };
  }

  async createProject(name: string) {
    const res = await this.request("POST", "/projects", SERVICE_TOKEN, { name });
    if (res.status !== 201) throw new Error(`createProject ${res.status}`);
    return created.parse(res.json);
  }

  async enroll(projectId: string, workstationId = "ws-design-01") {
    const res = await this.request("POST", `/projects/${projectId}/workstations`, SERVICE_TOKEN, {
      workstation_id: workstationId,
    });
    if (res.status !== 201) throw new Error(`enroll ${res.status}`);
    return enrolled.parse(res.json);
  }

  async postEnvelope(projectId: string, payload: unknown) {
    return this.request("POST", `/projects/${projectId}/envelopes`, SERVICE_TOKEN, payload);
  }

  async postEnvelopeExpect202(projectId: string, payload: unknown) {
    const res = await this.postEnvelope(projectId, payload);
    if (res.status !== 202) throw new Error(`postEnvelope ${res.status}: ${JSON.stringify(res.json)}`);
    return issued.parse(res.json);
  }

  async state(projectId: string) {
    const res = await this.request("GET", `/projects/${projectId}/state`, SERVICE_TOKEN);
    if (res.status !== 200) throw new Error(`state ${res.status}`);
    return stateSchema.parse(res.json);
  }

  async listReviews(projectId: string) {
    const res = await this.request("GET", `/projects/${projectId}/reviews`, ACTOR_TOKEN);
    if (res.status !== 200) throw new Error(`reviews ${res.status}`);
    return reviews.parse(res.json).reviews;
  }

  async approveReview(
    reviewId: string,
    confirmations?: { unit?: string; ceiling_height_mm?: number },
  ) {
    const res = await this.request("POST", `/reviews/${reviewId}/approve`, ACTOR_TOKEN,
      confirmations ? { confirmations } : {});
    if (res.status !== 200) throw new Error(`approve ${res.status}: ${JSON.stringify(res.json)}`);
  }

  async postScanBundle(projectId: string, dxfBase64: string, extra: Record<string, unknown> = {}) {
    const res = await this.request("POST", `/projects/${projectId}/scan-bundles`, SERVICE_TOKEN, {
      dxf_base64: dxfBase64,
      ...extra,
    });
    if (res.status !== 201) throw new Error(`scan-bundle ${res.status}: ${JSON.stringify(res.json)}`);
    return z
      .object({
        review_id: z.string(),
        content_hash: z.string(),
        status: z.string(),
        counts: z.object({ walls: z.number(), doors: z.number(), windows: z.number() }),
      })
      .parse(res.json);
  }

  async issueCommit0(projectId: string) {
    return this.request("POST", `/projects/${projectId}/issue-commit0`, SERVICE_TOKEN, {});
  }

  raw(method: string, path: string, token: string | null, body?: unknown) {
    return this.request(method, path, token, body);
  }

  /** Poll project state until the predicate holds (commit_result arrives async). */
  async waitForState(
    projectId: string,
    predicate: (s: z.infer<typeof stateSchema>) => boolean,
    timeoutMs = 20_000,
  ) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const s = await this.state(projectId);
      if (predicate(s)) return s;
      if (Date.now() > deadline) throw new Error(`state predicate timeout: ${JSON.stringify(s)}`);
      await new Promise((r) => setTimeout(r, 200));
    }
  }
}

export const WALL_OPS = [1, 2, 3, 4].map((i) => ({
  op: "create_wall",
  args: {
    id: `W-00${i}`,
    start: [[0, 0], [4000, 0], [4000, 3000], [0, 3000]][i - 1],
    end: [[4000, 0], [4000, 3000], [0, 3000], [0, 0]][i - 1],
    revit_type: "CHPT_Partition_92mm_PLACEHOLDER",
    height: 2700,
    phase: "new",
  },
}));
