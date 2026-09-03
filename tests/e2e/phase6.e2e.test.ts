// Phase 6 acceptance, end to end: the full chain through the approved interior
// branch (phases 2->3->4->5 against real children), then the deterministic MEP agent
// (plan-mep -> mep_plan), the merge gate (merge-commit2 -> commit2_merge) and Commit
// #2 — with Phase B recovery driven by the sim's inject_clash control verb: the
// executor rolls the merged envelope back with `interference` twice, every rebuilt
// plan is a new human approval under the shared budget, the third merged envelope
// commits under a fresh seq; a second project exhausts the budget → REVIEW → a new
// mep_plan starts a fresh chain. Five real child processes; the sim runs with its
// control port (the only place the deterministic clash stimulus exists).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi } from "./src/api.js";
import {
  REPO_ROOT, cleanupDir, controlCommand, startBriefExtractor, startConverter, startGateway,
  startLayoutCompiler, startSim, stop,
  type ConverterProc, type GatewayProc, type SimProc,
} from "./src/harness.js";

const DATABASE_URL = process.env["DATABASE_URL"] ?? "postgres://chapter:chapter@127.0.0.1:5432/revit_agent";
const GOLDENS = join(REPO_ROOT, "fixtures", "goldens");
const golden = (name: string) => readFileSync(join(GOLDENS, name), "utf8");
// the card's human-suppliable confirmations (golden_mep.py CONFIRMATIONS)
const CONFIRMATIONS = { panel: [8050, 5200] as [number, number], slab_to_slab_mm: 3000 };

let converter: ConverterProc;
let extractor: ConverterProc;
let compiler: ConverterProc;
let gateway: GatewayProc;
let sim: SimProc | null = null;
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
  await stopSim();
  await stop(gateway.proc);
  await Promise.all([stop(converter.proc), stop(extractor.proc), stop(compiler.proc)]);
});

async function stopSim(): Promise<void> {
  if (!sim) return;
  await stop(sim.proc);
  cleanupDir(sim.stateDir);
  sim = null;
}

/** Phases 2–5 for a fresh project with its own sim: returns once the interior
 *  branch is approved (interior_plan_ready) and the model sits at Commit #1. */
async function chainToInterior(name: string): Promise<string> {
  const project = await api.createProject(name);
  const { token } = await api.enroll(project.id);
  sim = startSim(gateway.port, token, { controlPort: true });
  await sim.ready;
  await api.waitForState(project.id, (s) => s.executor_connected);

  const dxf = readFileSync(join(REPO_ROOT, "fixtures", "scans", "2br_uws.dxf"));
  const bundle = await api.postScanBundle(project.id, dxf.toString("base64"));
  await api.approveReview(bundle.review_id, { ceiling_height_mm: 2700 });
  expect((await api.issueCommit0(project.id)).status).toBe(202);
  await api.waitForState(project.id, (s) => s.commit0_done);

  const transcripts = join(REPO_ROOT, "fixtures", "transcripts");
  const uploaded = await api.postTranscripts(project.id, [
    { session_id: "session1_3br", text: readFileSync(join(transcripts, "session1_3br.txt"), "utf8") },
    { session_id: "session2_4br", text: readFileSync(join(transcripts, "session2_4br.txt"), "utf8") },
  ]);
  await api.approveReview(uploaded.review_id);
  const compileRes = await api.compileLayout(project.id);
  expect(compileRes.status).toBe(201);
  await api.approveReview((compileRes.json as { review_id: string }).review_id);
  expect((await api.issueCommit1(project.id)).status).toBe(202);
  await api.waitForState(project.id, (s) => s.commit1_done);

  const furnished = await api.furnishLayout(project.id);
  expect(furnished.status).toBe(201);
  await api.approveReview((furnished.json as { review_id: string }).review_id);
  await api.waitForState(project.id, (s) => s.interior_plan_ready);
  return project.id;
}

async function approvedMerge(projectId: string): Promise<{ reviewId: string; body: Record<string, unknown> }> {
  const res = await api.mergeCommit2(projectId);
  expect(res.status, JSON.stringify(res.json)).toBe(201);
  const body = res.json as Record<string, unknown>;
  await api.approveReview(body["review_id"] as string);
  return { reviewId: body["review_id"] as string, body };
}

it("recovers after two rolled-back Commit #2 envelopes: plan 3 commits at seq 5", async () => {
  const projectId = await chainToInterior("phase6-recovery");

  // ---- MEP agent: the flag-free, riser-free chain needs the card's confirmations ----
  const blocked = await api.planMep(projectId);
  expect(blocked.status).toBe(201);
  const blockedBody = blocked.json as { review_id: string; blocking: string[] };
  expect(blockedBody.blocking).toEqual(["levels_missing", "panel_missing"]);
  await api.approveReview(blockedBody.review_id);
  expect((await api.state(projectId)).mep_plan_ready).toBe(false); // approved but blocking
  const refused = await api.mergeCommit2(projectId);
  expect(refused.status).toBe(409);
  expect((refused.json as { error: string }).error).toBe("mep_review_items_open");

  const planned = await api.planMep(projectId, CONFIRMATIONS);
  expect(planned.status).toBe(201);
  const plannedBody = planned.json as {
    review_id: string; blocking: string[];
    counts: { stacks: number; pipes: number; devices: number; conduits: number };
  };
  expect(plannedBody.blocking).toEqual([]);
  expect(plannedBody.counts).toMatchObject({ stacks: 2, pipes: 10, devices: 45, conduits: 81 });
  const mepContent = await api.reviewContent(projectId, plannedBody.review_id);
  const goldenPlan = JSON.parse(golden("phase6_2br_mep.json")) as { ops: unknown[] };
  expect(mepContent["ops"]).toEqual(goldenPlan.ops); // the MEP half of Commit #2, byte-golden
  expect((mepContent["svgs"] as { mep: string; furnished: string }).mep).toBe(golden("phase6_2br_mep.svg"));
  expect((mepContent["svgs"] as { furnished: string }).furnished).toBe(golden("phase5_2br_furnished.svg"));
  await api.approveReview(plannedBody.review_id);
  await api.waitForState(projectId, (s) => s.mep_plan_ready);

  // ---- merge plan 1: clean, the golden clash report ----
  const plan1 = await approvedMerge(projectId);
  expect(plan1.body).toMatchObject({ iteration: 1, iterations_used: 0 });
  const plan1Content = await api.reviewContent(projectId, plan1.reviewId);
  const goldenReport = JSON.parse(golden("phase6_2br_clash_report.json")) as { clash_report: unknown; counts: unknown };
  expect(plan1Content["clash_report"]).toEqual(goldenReport.clash_report);
  expect(plan1Content["counts"]).toEqual(goldenReport.counts);
  expect((plan1Content["svgs"] as { merged: string }).merged).toBe(golden("phase6_2br_mep.svg"));
  expect((plan1Content["interior"] as { ops_verbatim: boolean }).ops_verbatim).toBe(true);

  // ---- Phase B: the executor rejects the next two merged envelopes on E-001~P-001 ----
  expect((await controlCommand(sim!.controlPort!, "inject_clash 2 E-001 P-001")).trim()).toBe("ok");
  let last = plan1;
  const offsets: number[] = [];
  for (let reject = 1; reject <= 2; reject++) {
    const issued = await api.issueCommit2(projectId);
    expect(issued.status, JSON.stringify(issued.json)).toBe(202);
    expect((issued.json as { seq: number }).seq).toBe(2 + reject);
    const state = await api.waitForState(
      projectId,
      (s) => s.commit2.envelope_status === "rolled_back" && (s.commit2.clash_pairs?.length ?? 0) > 0,
    );
    expect(state.commit2.clash_pairs).toEqual([{ a_id: "E-001", b_id: "P-001", kind: "hard_interference" }]);
    expect(state.commit2.merge_review_id).toBe(last.reviewId);
    expect(state.commit2_done).toBe(false);
    expect(state.last_committed_seq).toBe(2); // the snapshot stays at Commit #1
    // the consumed plan cannot be re-issued; the rebuilt plan is a NEW review
    expect(((await api.issueCommit2(projectId)).json as { error: string }).error).toBe("merge_review_consumed");
    last = await approvedMerge(projectId);
    expect(last.body).toMatchObject({ iteration: reject + 1, iterations_used: reject });
    const content = await api.reviewContent(projectId, last.reviewId);
    const actions = content["actions"] as { action: string; lower: string; params: { after: { offset: number } } }[];
    expect(actions.map((a) => [a.action, a.lower])).toEqual([["shift_device", "E-001"]]);
    offsets.push(actions[0]!.params.after.offset);
    const ops = content["ops"] as { args: { id?: string; offset?: number } }[];
    expect(ops.find((o) => o.args.id === "E-001")!.args.offset).toBe(actions[0]!.params.after.offset);
    expect((content["interior"] as { ops_verbatim: boolean }).ops_verbatim).toBe(true);
  }
  expect(offsets).toEqual([1762.5, 1612.5]); // away from P-001, 150 per round

  // ---- plan 3 commits under a fresh seq ----
  const final = await api.issueCommit2(projectId);
  expect(final.status).toBe(202);
  expect((final.json as { seq: number }).seq).toBe(5);
  const done = await api.waitForState(projectId, (s) => s.commit2_done);
  expect(done.last_committed_seq).toBe(5);
  expect(done.commit2).toMatchObject({
    iteration: 3, iterations_used: 2, budget_remaining: 1, envelope_status: "committed",
    exhausted: false, failed: false, merge_current: true,
  });
  expect(done.recent_envelopes.map((e) => [e.seq, e.status])).toEqual([
    [5, "committed"], [4, "rolled_back"], [3, "rolled_back"], [2, "committed"], [1, "committed"],
  ]);
  const plan3Content = await api.reviewContent(projectId, last.reviewId);
  expect((plan3Content["svgs"] as { merged: string }).merged).toBe(golden("phase6_2br_recovery.svg"));
  // the sim's own render of the committed model IS the recovery golden
  expect(readFileSync(join(sim!.stateDir, "blobs", "current_plan.svg"), "utf8")).toBe(golden("phase6_2br_recovery.svg"));
  // branches retained; three merged plans each approved by a human; no failure card
  const rows = await api.listReviewRows(projectId);
  const byKind = (kind: string) => rows.filter((r) => r.kind === kind);
  expect(byKind("interior_plan").map((r) => r.status)).toEqual(["approved"]);
  expect(byKind("mep_plan").map((r) => r.status).sort()).toEqual(["approved", "approved"]);
  expect(byKind("commit2_merge").map((r) => r.status)).toEqual(["approved", "approved", "approved"]);
  expect(byKind("commit2_failure")).toEqual([]);
  // every Commit #2 route is closed now
  for (const res of [await api.planMep(projectId, CONFIRMATIONS), await api.mergeCommit2(projectId), await api.issueCommit2(projectId), await api.furnishLayout(projectId)]) {
    expect((res.json as { error: string }).error).toBe("commit2_already_done");
  }
  await stopSim();
}, 300_000);

it("budget exhaustion → REVIEW → a new mep_plan starts a fresh chain", async () => {
  const projectId = await chainToInterior("phase6-exhaustion");
  const planned = await api.planMep(projectId, CONFIRMATIONS);
  expect(planned.status).toBe(201);
  await api.approveReview((planned.json as { review_id: string }).review_id);
  await approvedMerge(projectId);
  expect((await controlCommand(sim!.controlPort!, "inject_clash 4 E-001 P-001")).trim()).toBe("ok");
  for (let reject = 1; reject <= 4; reject++) {
    const issued = await api.issueCommit2(projectId);
    expect(issued.status, JSON.stringify(issued.json)).toBe(202);
    expect((issued.json as { seq: number }).seq).toBe(2 + reject);
    await api.waitForState(projectId, (s) => s.commit2.envelope_status === "rolled_back" && (s.commit2.clash_pairs?.length ?? 0) > 0);
    if (reject < 4) {
      const rebuilt = await approvedMerge(projectId);
      expect(rebuilt.body).toMatchObject({ iteration: reject + 1, iterations_used: reject });
    }
  }
  // the fourth rollback finds the budget spent: REVIEW, never a fifth plan
  const exhausted = await api.mergeCommit2(projectId);
  expect(exhausted.status).toBe(409);
  expect(exhausted.json).toEqual({ error: "merge_budget_exhausted", iterations_used: 3 });
  let state = await api.state(projectId);
  expect(state.commit2).toMatchObject({ exhausted: true, budget_remaining: 0, iterations_used: 3, envelope_status: "rolled_back" });
  expect(state.commit2_done).toBe(false);
  expect(state.last_committed_seq).toBe(2);
  const failures = (await api.listReviewRows(projectId)).filter((r) => r.kind === "commit2_failure");
  expect(failures.map((r) => [r.status, r.content["reason"]])).toEqual([["pending", "merge_budget_exhausted"]]);
  // a new mep_plan (confirmations carried forward) starts a FRESH chain with a fresh budget
  const replanned = await api.planMep(projectId);
  expect(replanned.status).toBe(201);
  await api.approveReview((replanned.json as { review_id: string }).review_id);
  expect(((await api.issueCommit2(projectId)).json as { error: string }).error).toBe("merge_review_stale");
  const fresh = await approvedMerge(projectId);
  expect(fresh.body).toMatchObject({ iteration: 1, iterations_used: 0 });
  state = await api.state(projectId);
  expect(state.commit2).toMatchObject({ exhausted: false, iterations_used: 0, budget_remaining: 3, merge_current: true });
  // and the fresh plan commits (the injected clashes are spent)
  const issued = await api.issueCommit2(projectId);
  expect(issued.status).toBe(202);
  expect((issued.json as { seq: number }).seq).toBe(7);
  const done = await api.waitForState(projectId, (s) => s.commit2_done);
  expect(done.last_committed_seq).toBe(7);
  await stopSim();
}, 300_000);
