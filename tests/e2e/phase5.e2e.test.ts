// Phase 5 acceptance, end to end: the full chain through Commit #1 (phases
// 2->3->4 flows against real children), then furnish-layout — the real
// compiler service replays the recorded 4BR furniture emission, the real
// Part G placer legalizes it, and the gateway stores the interior_plan BRANCH
// DELTA (Phase 5 issues NO envelope; Phase 6's merge gate consumes the
// approved review). Five real child processes.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi } from "./src/api.js";
import {
  ACTOR_TOKEN, REPO_ROOT, cleanupDir, startBriefExtractor, startConverter, startGateway,
  startLayoutCompiler, startSim, stop,
  type ConverterProc, type GatewayProc, type SimProc,
} from "./src/harness.js";

const DATABASE_URL = process.env["DATABASE_URL"] ?? "postgres://chapter:chapter@127.0.0.1:5432/revit_agent";

let converter: ConverterProc;
let extractor: ConverterProc;
let compiler: ConverterProc;
let gateway: GatewayProc;
let sim: SimProc;
let api: GatewayApi;

beforeAll(async () => {
  [converter, extractor, compiler] = await Promise.all([
    startConverter(), startBriefExtractor(), startLayoutCompiler(),
  ]);
  gateway = await startGateway(DATABASE_URL, {
    SCAN_CONVERTER_URL: converter.url,
    BRIEF_EXTRACTOR_URL: extractor.url,
    LAYOUT_COMPILER_URL: compiler.url,
  });
  api = new GatewayApi(gateway.url);
}, 60_000);

afterAll(async () => {
  if (sim) await stop(sim.proc);
  await stop(gateway.proc);
  await Promise.all([stop(converter.proc), stop(extractor.proc), stop(compiler.proc)]);
  if (sim) cleanupDir(sim.stateDir);
});

it("chain to Commit #1, then furnish -> interior_plan branch delta + golden card", async () => {
  const project = await api.createProject("phase5-interior");
  const { token } = await api.enroll(project.id);
  sim = startSim(gateway.port, token);
  await sim.ready;
  await api.waitForState(project.id, (s) => s.executor_connected);

  // ---- Commit #0 (ceiling 2700 = the golden heights; flags stay unconfirmed:
  //      the golden fixture chain is deliberately flag-free) ----
  const dxf = readFileSync(join(REPO_ROOT, "fixtures", "scans", "2br_uws.dxf"));
  const bundle = await api.postScanBundle(project.id, dxf.toString("base64"));
  await api.approveReview(bundle.review_id, { ceiling_height_mm: 2700 });
  expect((await api.issueCommit0(project.id)).status).toBe(202);
  await api.waitForState(project.id, (s) => s.commit0_done);

  // furnishing before Commit #1 refuses
  const early = await api.furnishLayout(project.id);
  expect(early.status).toBe(409);
  expect((early.json as { error: string }).error).toBe("commit1_not_done");

  // ---- brief + Commit #1 (phase 3 + 4 flows) ----
  const transcripts = join(REPO_ROOT, "fixtures", "transcripts");
  const uploaded = await api.postTranscripts(project.id, [
    { session_id: "session1_3br", text: readFileSync(join(transcripts, "session1_3br.txt"), "utf8") },
    { session_id: "session2_4br", text: readFileSync(join(transcripts, "session2_4br.txt"), "utf8") },
  ]);
  await api.approveReview(uploaded.review_id);
  const compileRes = await api.compileLayout(project.id);
  expect(compileRes.status).toBe(201);
  const compileReviewId = (compileRes.json as { review_id: string }).review_id;
  await api.approveReview(compileReviewId);
  expect((await api.issueCommit1(project.id)).status).toBe(202);
  await api.waitForState(project.id, (s) => s.commit1_done);

  // ---- furnish: real compiler + recorded emission + real placer ----
  const furnished = await api.furnishLayout(project.id);
  expect(furnished.status).toBe(201);
  const body = furnished.json as {
    review_id: string;
    status: string;
    counts: { items_placed: number; items_unplaced: number; rooms_furnished: number };
  };
  expect(body.status).toBe("pending");
  expect(body.counts).toEqual({ items_placed: 18, items_unplaced: 2, rooms_furnished: 8 });

  const content = await api.reviewContent(project.id, body.review_id);
  const ops = content["ops"] as { op: string; args: { id: string } }[];
  expect(ops).toHaveLength(18);
  expect(new Set(ops.map((o) => o.op))).toEqual(new Set(["place_family"]));
  const unplaced = content["unplaced"] as { item: { id: string }; reason: string }[];
  // the REVIEW demos, in the placer's global (-area, id) attempt order
  expect(unplaced.map((u) => u.item.id)).toEqual(["F-020", "F-013"]);
  for (const entry of unplaced) expect(entry.reason).toBeTruthy();
  const diagnostics = content["diagnostics"] as {
    items: { candidates_per_wall: Record<string, number>; spiral_tried: number }[];
  };
  for (const diag of diagnostics.items) {
    expect(Object.values(diag.candidates_per_wall).every((n) => n <= 162)).toBe(true);
    expect(diag.spiral_tried).toBeLessThanOrEqual(324);
  }

  // the card panes ARE reality: left byte-equals the Phase 4 golden (post-
  // Commit-#1 sim state), right byte-equals the furnished golden (eyeballed)
  const svgs = content["svgs"] as { commit1: string; furnished: string };
  expect(svgs.commit1).toBe(
    readFileSync(join(REPO_ROOT, "fixtures", "goldens", "phase4_2br.svg"), "utf8"),
  );
  expect(svgs.furnished).toBe(
    readFileSync(join(REPO_ROOT, "fixtures", "goldens", "phase5_2br_furnished.svg"), "utf8"),
  );

  // Phase 5 commits NOTHING: no new envelope, the model still sits at seq 2,
  // and the branch delta becomes consumable only on approval
  let state = await api.state(project.id);
  expect(state.last_committed_seq).toBe(2);
  expect(state.interior_plan_ready).toBe(false);
  await api.approveReview(body.review_id);
  state = await api.state(project.id);
  expect(state.interior_plan_ready).toBe(true);
  expect(state.last_committed_seq).toBe(2);
  expect(state.recent_envelopes).toHaveLength(2); // Commit #0 + Commit #1 only

  // the review card renders for the human
  const page = await api.raw(
    "GET", `/ui/projects/${project.id}/reviews?actor_token=${ACTOR_TOKEN}`, ACTOR_TOKEN,
  );
  expect(page.status).toBe(200);
}, 120_000);
