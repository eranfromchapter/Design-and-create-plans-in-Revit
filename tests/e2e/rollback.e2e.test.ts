// Phase 1 acceptance: two envelopes where the second fails → first committed, second
// rolled back ALONE, per-envelope commit_result; the failed seq is re-issued.
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi, WALL_OPS } from "./src/api.js";
import {
  cleanupDir, startGateway, startSim, stop, type GatewayProc, type SimProc,
} from "./src/harness.js";

const DATABASE_URL = process.env["DATABASE_URL"] ?? "postgres://chapter:chapter@127.0.0.1:5432/revit_agent";

let gateway: GatewayProc;
let sim: SimProc;
let api: GatewayApi;

beforeAll(async () => {
  gateway = await startGateway(DATABASE_URL);
  api = new GatewayApi(gateway.url);
});

afterAll(async () => {
  if (sim) await stop(sim.proc);
  await stop(gateway.proc);
  if (sim) cleanupDir(sim.stateDir);
});

it("second envelope rolls back alone; its seq is re-issuable", async () => {
  const project = await api.createProject("phase1-rollback");
  const { token } = await api.enroll(project.id);
  sim = startSim(gateway.port, token);
  await sim.ready;
  await api.waitForState(project.id, (s) => s.executor_connected);

  await api.postEnvelopeExpect202(project.id, { ops: WALL_OPS });
  await api.waitForState(project.id, (s) => s.last_committed_seq === 1);

  // duplicate wall id → executor rolls the whole envelope back
  const bad = await api.postEnvelopeExpect202(project.id, {
    ops: [WALL_OPS[0]], // W-001 again
  });
  expect(bad.seq).toBe(2);
  let state = await api.waitForState(project.id, (s) =>
    s.recent_envelopes.some((e) => e.status === "rolled_back"),
  );
  expect(state.last_committed_seq).toBe(1);
  expect(Object.keys(state.id_map)).toHaveLength(4); // first envelope intact

  // seq 2 is re-issued and commits (rollback released it)
  const retry = await api.postEnvelopeExpect202(project.id, {
    ops: [{
      op: "create_wall",
      args: {
        id: "W-005", start: [0, 6000], end: [4000, 6000],
        revit_type: "CHPT_Partition_92mm_PLACEHOLDER", height: 2700, phase: "new",
      },
    }],
  });
  expect(retry.seq).toBe(2);
  state = await api.waitForState(project.id, (s) => s.last_committed_seq === 2);
  expect(state.id_map["W-005"]).toBe(1000005);
});
