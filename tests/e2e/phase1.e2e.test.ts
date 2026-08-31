// Phase 1 acceptance, first checkbox: gateway signs an envelope with 4 create_wall ops
// → revit-sim commits → commit_result recorded → sim SVG matches the golden (byte-equal;
// the renderer is canonical by construction).
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, expect, it } from "vitest";
import { idMapHash } from "@chapter/contracts";
import { GatewayApi, WALL_OPS } from "./src/api.js";
import {
  REPO_ROOT, cleanupDir, startGateway, startSim, stop,
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

it("4-wall golden pipeline: POST → sign → WSS → sim commit → id_map → SVG golden", async () => {
  const project = await api.createProject("phase1-golden");
  const { token } = await api.enroll(project.id);
  sim = startSim(gateway.port, token);
  await sim.ready;

  await api.waitForState(project.id, (s) => s.executor_connected);
  const { seq } = await api.postEnvelopeExpect202(project.id, {
    ops: WALL_OPS,
    commit_label: "phase 1 golden walls",
  });
  expect(seq).toBe(1);

  const state = await api.waitForState(project.id, (s) => s.last_committed_seq === 1);
  expect(state.recent_envelopes[0]!.status).toBe("committed");
  expect(state.id_map).toEqual({
    "W-001": 1000001, "W-002": 1000002, "W-003": 1000003, "W-004": 1000004,
  });
  expect(state.id_map_hash).toBe(idMapHash(state.id_map));
  expect(state.drift_state).toBe("clean");

  // golden SVG: canonical bytes from the sim's renderer
  const svgPath = join(sim.stateDir, "blobs", "current_plan.svg");
  const svg = readFileSync(svgPath, "utf8");
  const goldenPath = join(REPO_ROOT, "fixtures", "goldens", "phase1_4walls.svg");
  if (!existsSync(goldenPath)) {
    throw new Error(`golden missing: ${goldenPath} — generate once via 'make demo-phase1' and eyeball it`);
  }
  const golden = readFileSync(goldenPath, "utf8");
  expect(svg).toBe(golden);
});
