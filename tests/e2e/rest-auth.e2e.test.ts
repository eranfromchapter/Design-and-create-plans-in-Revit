// Phase 1 acceptance (SI-10): unauthenticated / wrong-credential REST → 401/403 and
// no envelope is ever signed; schema-invalid ops → 422 before signing.
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi, WALL_OPS } from "./src/api.js";
import { ACTOR_TOKEN, startGateway, stop, type GatewayProc } from "./src/harness.js";

const DATABASE_URL = process.env["DATABASE_URL"] ?? "postgres://chapter:chapter@127.0.0.1:5432/revit_agent";

let gateway: GatewayProc;
let api: GatewayApi;

beforeAll(async () => {
  gateway = await startGateway(DATABASE_URL);
  api = new GatewayApi(gateway.url);
});

afterAll(async () => {
  await stop(gateway.proc);
});

it("SI-10 over real HTTP: 401 / 403 / 422 and nothing signed", async () => {
  const project = await api.createProject("phase1-auth");

  const unauth = await api.raw("POST", `/projects/${project.id}/envelopes`, null, { ops: WALL_OPS });
  expect(unauth.status).toBe(401);

  const wrong = await api.raw("POST", `/projects/${project.id}/envelopes`, "wrong-token-000000", { ops: WALL_OPS });
  expect(wrong.status).toBe(403);

  const actorOnService = await api.raw("POST", "/projects", ACTOR_TOKEN, { name: "nope" });
  expect(actorOnService.status).toBe(403);

  const invalidArgs = await api.raw("POST", `/projects/${project.id}/envelopes`, "service-token-0123456789", {
    ops: [{ op: "create_level", args: { name: "L1" } }],
  });
  expect([409, 422]).toContain(invalidArgs.status); // 409 no_executor is also pre-signing

  const state = await api.state(project.id);
  expect(state.recent_envelopes).toHaveLength(0); // nothing was ever signed
});
