// Drift gate end-to-end: the sim's control hook injects the DocumentChangedWatcher
// signal (state_divergence) → project dirty + pending drift review → envelope POST 409
// → human approves via REST → envelopes flow again.
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi, WALL_OPS } from "./src/api.js";
import {
  cleanupDir, controlCommand, startGateway, startSim, stop,
  type GatewayProc, type SimProc,
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

it("state_divergence → dirty + review → 409 → approve → flow resumes", async () => {
  const project = await api.createProject("phase1-drift");
  const { token } = await api.enroll(project.id);
  sim = startSim(gateway.port, token, { controlPort: true });
  await sim.ready;
  await api.waitForState(project.id, (s) => s.executor_connected);

  await api.postEnvelopeExpect202(project.id, { ops: WALL_OPS });
  await api.waitForState(project.id, (s) => s.last_committed_seq === 1);

  // inject the divergence signal (what DocumentChangedWatcher sends on a manual edit)
  expect(await controlCommand(sim.controlPort!, "diverge")).toBe("ok");
  const dirty = await api.waitForState(project.id, (s) => s.drift_state === "dirty");
  expect(dirty.pending_reviews).toBe(1);

  const blocked = await api.postEnvelope(project.id, { ops: [{ op: "create_level", args: { name: "L2", elevation: 3000 } }] });
  expect(blocked.status).toBe(409);
  expect((blocked.json as { error: string }).error).toBe("drift_review_pending");

  const review = (await api.listReviews(project.id)).find(
    (r) => r.kind === "drift" && r.status === "pending",
  )!;
  await api.approveReview(review.id);

  const after = await api.waitForState(project.id, (s) => s.drift_state === "clean");
  expect(after.pending_reviews).toBe(0);
  // NOTE: the sim's local id-map is deliberately perturbed by the hook; approving a drift
  // review means "human accepted the divergence for now" (full resync lands in Phase 2).
  // The gate is what's under test: the envelope path is open again.
  const resumed = await api.postEnvelope(project.id, { ops: [{ op: "create_level", args: { name: "L2", elevation: 3000 } }] });
  expect(resumed.status).toBe(202);
});
