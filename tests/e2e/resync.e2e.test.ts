// Phase 1 acceptance: sim killed mid-stream → restarted over the same state dir →
// hello resync from the PERSISTED seq/hash → next envelope proceeds, no drift review.
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi, WALL_OPS } from "./src/api.js";
import {
  cleanupDir, sleep, startGateway, startSim, stop, type GatewayProc, type SimProc,
} from "./src/harness.js";

const DATABASE_URL = process.env["DATABASE_URL"] ?? "postgres://chapter:chapter@127.0.0.1:5432/revit_agent";

let gateway: GatewayProc;
let sim: SimProc | undefined;
let stateDir: string | undefined;
let api: GatewayApi;

beforeAll(async () => {
  gateway = await startGateway(DATABASE_URL);
  api = new GatewayApi(gateway.url);
});

afterAll(async () => {
  if (sim) await stop(sim.proc);
  await stop(gateway.proc);
  if (stateDir) cleanupDir(stateDir);
});

it("SIGKILL mid-stream → restart → hello resync → next envelope commits", async () => {
  const project = await api.createProject("phase1-resync");
  const { token } = await api.enroll(project.id);
  sim = startSim(gateway.port, token);
  stateDir = sim.stateDir;
  await sim.ready;
  await api.waitForState(project.id, (s) => s.executor_connected);

  await api.postEnvelopeExpect202(project.id, { ops: WALL_OPS });
  await api.waitForState(project.id, (s) => s.last_committed_seq === 1);

  await stop(sim.proc, "SIGKILL");
  await api.waitForState(project.id, (s) => !s.executor_connected);
  await sleep(200);

  // restart over the SAME state dir: hello must report seq=1 + the committed hash
  sim = startSim(gateway.port, token, { stateDir });
  await sim.ready;
  const state = await api.waitForState(project.id, (s) => s.executor_connected);
  expect(state.drift_state).toBe("clean"); // resync matched — no drift review
  expect(state.pending_reviews).toBe(0);

  const next = await api.postEnvelopeExpect202(project.id, {
    ops: [{
      op: "create_level", args: { name: "L2", elevation: 3000 },
    }],
  });
  expect(next.seq).toBe(2);
  await api.waitForState(project.id, (s) => s.last_committed_seq === 2);
});
