// Phase 4 acceptance, end to end: the full chain. Commit #0 via the Phase 2
// flow (DXF → converter → approve → sim commit), the confirmed brief via the
// Phase 3 flow (transcripts → extractor → approve), then compile-layout (real
// compiler replaying the recorded 4BR emission) → layout_commit1 review →
// approve → issue-commit1 → sim commit → demolished walls dashed in the golden
// SVG, the frozen commit1 snapshot, and the review card's new_svg byte-equal
// to post-commit reality. Five real child processes.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi } from "./src/api.js";
import {
  REPO_ROOT, cleanupDir, startBriefExtractor, startConverter, startGateway,
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

it("brief + Commit #0 → compile → approve → Commit #1 → golden SVG + frozen snapshot", async () => {
  const project = await api.createProject("phase4-layout");
  const { token } = await api.enroll(project.id);
  sim = startSim(gateway.port, token);
  await sim.ready;
  await api.waitForState(project.id, (s) => s.executor_connected);

  // ---- gating: nothing compiles before Commit #0 ----
  const early = await api.compileLayout(project.id);
  expect(early.status).toBe(409);
  expect((early.json as { error: string }).error).toBe("commit0_not_done");

  // ---- Commit #0 via the Phase 2 flow (ceiling 2700 = the fixture heights) ----
  const dxf = readFileSync(join(REPO_ROOT, "fixtures", "scans", "2br_uws.dxf"));
  const bundle = await api.postScanBundle(project.id, dxf.toString("base64"));
  await api.approveReview(bundle.review_id, { ceiling_height_mm: 2700 });
  expect((await api.issueCommit0(project.id)).status).toBe(202);
  await api.waitForState(project.id, (s) => s.commit0_done);

  // ---- gating: a compile without a confirmed brief refuses ----
  const noBrief = await api.compileLayout(project.id);
  expect(noBrief.status).toBe(409);
  expect((noBrief.json as { error: string }).error).toBe("no_brief");

  // ---- the brief via the Phase 3 flow ----
  const transcripts = join(REPO_ROOT, "fixtures", "transcripts");
  const uploaded = await api.postTranscripts(project.id, [
    { session_id: "session1_3br", text: readFileSync(join(transcripts, "session1_3br.txt"), "utf8") },
    { session_id: "session2_4br", text: readFileSync(join(transcripts, "session2_4br.txt"), "utf8") },
  ]);
  const unconfirmed = await api.compileLayout(project.id);
  expect((unconfirmed.json as { error: string }).error).toBe("brief_not_confirmed");
  await api.approveReview(uploaded.review_id);

  // ---- compile: real compiler, recorded 4BR emission, diff vs the FROZEN snapshot ----
  const compiled = await api.compileLayout(project.id);
  expect(compiled.status).toBe(201);
  const compileBody = compiled.json as {
    review_id: string;
    status: string;
    counts: { walls: number; rooms: number; demolished: number };
  };
  expect(compileBody.status).toBe("pending");
  expect(compileBody.counts).toMatchObject({ walls: 25, rooms: 11, demolished: 4 });

  const content = await api.reviewContent(project.id, compileBody.review_id);
  expect((content["demolition_list"] as { id: string }[]).map((d) => d.id)).toEqual([
    "D-002", "D-005", "W-007", "W-008",
  ]);

  // ---- mandatory human gate: issuing before approval refuses ----
  const notApproved = await api.issueCommit1(project.id);
  expect(notApproved.status).toBe(409);
  expect((notApproved.json as { error: string }).error).toBe("layout_review_not_approved");

  await api.approveReview(compileBody.review_id);
  const issued = await api.issueCommit1(project.id);
  expect(issued.status).toBe(202);
  expect((issued.json as { seq: number }).seq).toBe(2);

  const state = await api.waitForState(
    project.id,
    (s) => s.last_committed_seq === 2 && s.commit1_done,
  );
  expect(state.drift_state).toBe("clean");
  // id_map: 26 from Commit #0 + 10 new walls + 8 new doors (demolition maps nothing)
  expect(Object.keys(state.id_map)).toHaveLength(44);
  expect(state.id_map["W-027"]).toBeDefined();
  expect(state.id_map["D-013"]).toBeDefined();

  // ---- the golden: sim bytes == committed golden == the approved card's new_svg ----
  const svg = readFileSync(join(sim.stateDir, "blobs", "current_plan.svg"), "utf8");
  const goldenPath = join(REPO_ROOT, "fixtures", "goldens", "phase4_2br.svg");
  if (!existsSync(goldenPath)) {
    throw new Error(`golden missing: ${goldenPath} — generate via 'make demo-phase4' and eyeball it`);
  }
  expect(svg).toBe(readFileSync(goldenPath, "utf8"));
  expect((content["svgs"] as { new: string }).new).toBe(svg); // the card showed reality
  // demolition by phasing, visibly: dashed strokes, elements never deleted
  expect(svg).toContain('class="wall demolished"');
  expect(svg).toContain('class="door demolished"');
  expect(svg).toContain("stroke-dasharray");

  // ---- Commit #1 is once per project ----
  const again = await api.issueCommit1(project.id);
  expect(again.status).toBe(409);
  expect((again.json as { error: string }).error).toBe("commit1_already_done");
  const recompile = await api.compileLayout(project.id);
  expect(recompile.status).toBe(409);
  expect((recompile.json as { error: string }).error).toBe("commit1_already_done");
}, 120_000);
