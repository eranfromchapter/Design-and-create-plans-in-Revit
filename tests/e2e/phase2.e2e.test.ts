// Phase 2 acceptance, first checkbox: fixture DXF → converter → scan_commit0
// review (with unit + ceiling confirmations) → approve → issue-commit0 →
// Ed25519 envelope → sim commit → commit0_done + full id_map + golden SVG.
// Three real child processes: converter (FastAPI), gateway (tsx), sim (python).
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi } from "./src/api.js";
import {
  ACTOR_TOKEN, REPO_ROOT, SERVICE_TOKEN, cleanupDir, startConverter, startGateway, startSim, stop,
  type ConverterProc, type GatewayProc, type SimProc,
} from "./src/harness.js";

const DATABASE_URL = process.env["DATABASE_URL"] ?? "postgres://chapter:chapter@127.0.0.1:5432/revit_agent";

let converter: ConverterProc;
let gateway: GatewayProc;
let sim: SimProc;
let api: GatewayApi;

beforeAll(async () => {
  converter = await startConverter();
  gateway = await startGateway(DATABASE_URL, { SCAN_CONVERTER_URL: converter.url });
  api = new GatewayApi(gateway.url);
});

afterAll(async () => {
  if (sim) await stop(sim.proc);
  await stop(gateway.proc);
  await stop(converter.proc);
  if (sim) cleanupDir(sim.stateDir);
});

it("2BR DXF → review → approve(2700) → Commit #0 → golden SVG", async () => {
  const project = await api.createProject("phase2-lane-a");
  const { token } = await api.enroll(project.id);
  sim = startSim(gateway.port, token);
  await sim.ready;
  await api.waitForState(project.id, (s) => s.executor_connected);

  // upload the canonical fixture
  const dxf = readFileSync(join(REPO_ROOT, "fixtures", "scans", "2br_uws.dxf"));
  const bundle = await api.postScanBundle(project.id, dxf.toString("base64"));
  expect(bundle.status).toBe("pending");
  expect(bundle.counts).toEqual({ walls: 17, doors: 5, windows: 3 });

  const pending = (await api.listReviews(project.id)).find(
    (r) => r.kind === "scan_commit0" && r.status === "pending",
  );
  expect(pending?.id).toBe(bundle.review_id);

  // issuing before approval is refused
  const early = await api.issueCommit0(project.id);
  expect(early.status).toBe(409);
  expect((early.json as { error: string }).error).toBe("scan_review_not_approved");

  // approval requires the ceiling confirmation ($INSUNITS=4 → no unit confirmation)
  const bare = await api.raw("POST", `/reviews/${bundle.review_id}/approve`, ACTOR_TOKEN, {});
  expect(bare.status).toBe(422);
  await api.approveReview(bundle.review_id, { ceiling_height_mm: 2700 });

  const issued = await api.issueCommit0(project.id);
  expect(issued.status).toBe(202);
  const { seq } = issued.json as { seq: number };
  expect(seq).toBe(1);

  const state = await api.waitForState(
    project.id,
    (s) => s.last_committed_seq === 1 && s.commit0_done,
  );
  expect(state.drift_state).toBe("clean");
  // full id_map: 1 level + 17 walls + 5 doors + 3 windows
  expect(Object.keys(state.id_map)).toHaveLength(26);
  expect(state.id_map["Level 1"]).toBeDefined();
  expect(state.id_map["W-017"]).toBeDefined();
  expect(state.id_map["D-005"]).toBeDefined();
  expect(state.id_map["N-003"]).toBeDefined();

  // golden SVG: canonical bytes from the sim's renderer
  const svg = readFileSync(join(sim.stateDir, "blobs", "current_plan.svg"), "utf8");
  const goldenPath = join(REPO_ROOT, "fixtures", "goldens", "phase2_2br.svg");
  if (!existsSync(goldenPath)) {
    throw new Error(`golden missing: ${goldenPath} — generate once via 'make demo-phase2' and eyeball it`);
  }
  expect(svg).toBe(readFileSync(goldenPath, "utf8"));

  // Commit #0 is once per project: a second issue and a re-upload both refuse
  const again = await api.issueCommit0(project.id);
  expect(again.status).toBe(409);
  expect((again.json as { error: string }).error).toBe("commit0_already_done");
  const reupload = await api.raw(
    "POST", `/projects/${project.id}/scan-bundles`, SERVICE_TOKEN,
    { dxf_base64: dxf.toString("base64") },
  );
  expect(reupload.status).toBe(409);
});
