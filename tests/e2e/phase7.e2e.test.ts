// Phase 7 acceptance, end to end: the full chain to Commit #2 against real children
// (phases 2->3->4->5->6, clean merge), then export_views (the sim rasterises its canonical
// plan / section / axonometric SVGs into the gateway's blob dir and emits export_ready in
// views order), compose-render against the real AIDM bridge child (mock renderer) — the
// control-map refs ARE the sha256 strings pinned in fixtures/goldens/phase7_2br_render.json —
// the render_review approval, the golden structured finish selection -> finish_commit, and
// "Commit #3 finishes" committing at seq 5 with the approved set_parameter ops verbatim.
// Six real child processes; approvals are explicit (no AUTO_APPROVE); placeholder SKUs are
// allowed through the CI-only ALLOW_PLACEHOLDER_SKUS switch the harness opts into here.
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi } from "./src/api.js";
import {
  REPO_ROOT, SERVICE_TOKEN, cleanupDir, startAidmBridge, startBriefExtractor, startConverter, startGateway,
  startLayoutCompiler, startSim, stop,
  type ConverterProc, type GatewayProc, type SimProc,
} from "./src/harness.js";

const DATABASE_URL = process.env["DATABASE_URL"] ?? "postgres://chapter:chapter@127.0.0.1:5432/revit_agent";
const GOLDENS = join(REPO_ROOT, "fixtures", "goldens");
const golden = (name: string) => readFileSync(join(GOLDENS, name), "utf8");
const sha256 = (b: Buffer) => createHash("sha256").update(b).digest("hex");
const CONFIRMATIONS = { panel: [8050, 5200] as [number, number], slab_to_slab_mm: 3000 };
const VIEWS = ["plan", "section", "3d_hidden"] as const;

interface GoldenRender {
  control_maps: { name: string; kind: string; canny_png_base64: string; lines_png_base64: string; preview_png_base64: string; stats: Record<string, number> }[];
  prompt: { template_version: string; text: string; tags_used: string[]; tags_dropped: unknown[] };
  renders: { name: string; status: string }[];
  candidates: Record<string, unknown[]>;
  review_items: unknown[];
}
interface GoldenSelection {
  request: { selection: Record<string, unknown>; finish_tier: string; catalog_version: string };
  response: { ops: { op: string; args: { target_id: string; param: string; value: unknown } }[]; review_items: unknown[]; blocking: string[]; diagnostics: { counts: Record<string, number> } };
}

let converter: ConverterProc;
let extractor: ConverterProc;
let compiler: ConverterProc;
let bridge: ConverterProc;
let gateway: GatewayProc;
let sim: SimProc | null = null;
let api: GatewayApi;
let blobDir: string;

beforeAll(async () => {
  [converter, extractor, compiler, bridge] = await Promise.all([
    startConverter(), startBriefExtractor(), startLayoutCompiler(), startAidmBridge(),
  ]);
  // the sim's blob dir IS the gateway's blob store (shared FS; the plugin uploads instead)
  blobDir = mkdtempSync(join(tmpdir(), "phase7-blobs-"));
  gateway = await startGateway(DATABASE_URL, {
    SCAN_CONVERTER_URL: converter.url,
    BRIEF_EXTRACTOR_URL: extractor.url,
    LAYOUT_COMPILER_URL: compiler.url,
    AIDM_BRIDGE_URL: bridge.url,
    BLOB_DIR: blobDir,
    CI: "true",
    ALLOW_PLACEHOLDER_SKUS: "1",
  });
  api = new GatewayApi(gateway.url);
}, 90_000);

afterAll(async () => {
  await stopSim();
  await stop(gateway.proc);
  await Promise.all([stop(converter.proc), stop(extractor.proc), stop(compiler.proc), stop(bridge.proc)]);
  cleanupDir(blobDir);
});

async function stopSim(): Promise<void> {
  if (!sim) return;
  await stop(sim.proc);
  cleanupDir(sim.stateDir);
  sim = null;
}

/** Phases 2–6 (clean merge) for a fresh project with its own sim: the model sits at
 *  Commit #2 (seq 3) — the Phase 6 golden model the Phase 7 goldens were made from. */
async function chainToCommit2(name: string): Promise<{ projectId: string; token: string }> {
  const project = await api.createProject(name);
  const { token } = await api.enroll(project.id);
  sim = startSim(gateway.port, token, { blobDir });
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

  const planned = await api.planMep(project.id, CONFIRMATIONS);
  expect(planned.status, JSON.stringify(planned.json)).toBe(201);
  await api.approveReview((planned.json as { review_id: string }).review_id);
  await api.waitForState(project.id, (s) => s.mep_plan_ready);
  const merged = await api.mergeCommit2(project.id);
  expect(merged.status, JSON.stringify(merged.json)).toBe(201);
  await api.approveReview((merged.json as { review_id: string }).review_id);
  expect((await api.issueCommit2(project.id)).status).toBe(202);
  const done = await api.waitForState(project.id, (s) => s.commit2_done);
  expect(done.last_committed_seq).toBe(3);
  return { projectId: project.id, token };
}

it("export → compose (golden control maps) → render_review → golden finish selection → Commit #3 at seq 5", async () => {
  const { projectId, token } = await chainToCommit2("phase7");
  const goldenRender = JSON.parse(golden("phase7_2br_render.json")) as GoldenRender;
  const goldenSelection = JSON.parse(golden("phase7_2br_finish_selection.json")) as GoldenSelection;

  // ---- export: one envelope, three frames in views order, blobs in the shared dir ----
  let s = await api.state(projectId);
  expect(s.render).toBeNull();
  expect(s.render_exported).toBe(false);
  const rv = await api.renderViews(projectId);
  expect(rv.status, JSON.stringify(rv.json)).toBe(202);
  const { render_id: renderId, seq: exportSeq } = rv.json as { render_id: string; envelope_id: string; seq: number };
  expect(exportSeq).toBe(4); // the export consumes a seq (not commit-class: no approval)
  s = await api.waitForState(projectId, (st) => st.render_exported);
  expect(s.render).toMatchObject({ render_id: renderId, status: "exported", envelope_status: "committed", expected_views: 3, blob_refs: 3 });
  expect(s.last_committed_seq).toBe(4);
  expect(s.commit2_done).toBe(true); // nothing in the model changed
  // the sim's PNGs are the committed fixtures: rasterisations of the golden model's SVGs
  const fixturePngs = VIEWS.map((v) => readFileSync(join(REPO_ROOT, "fixtures", "renders", `phase7_2br_${v}_2048.png`)));
  for (const png of fixturePngs) {
    expect(readFileSync(join(blobDir, sha256(png))).equals(png)).toBe(true);
    const got = await api.getBlob(projectId, sha256(png));
    expect(got.status).toBe(200);
    expect(got.contentType).toBe("image/png");
    expect(sha256(got.bytes)).toBe(sha256(png));
  }

  // ---- compose: the real bridge child; control maps == the golden hashes ----
  const composed = await api.composeRender(projectId);
  expect(composed.status, JSON.stringify(composed.json)).toBe(201);
  const composedBody = composed.json as { review_id: string; status: string; counts: Record<string, number> };
  expect(composedBody.status).toBe("pending"); // explicit approval, no AUTO_APPROVE
  expect(composedBody.counts).toMatchObject({ views: 3, renders_ok: 3, tags_used: 3, tags_dropped: 0 });
  const content = await api.reviewContent(projectId, composedBody.review_id);
  expect(JSON.stringify(content)).not.toContain("_base64");
  expect(content["render_id"]).toBe(renderId);
  expect(content["layout_snapshot"]).toBe("commit2");
  expect(content["finish_tier"]).toBe(goldenSelection.request.finish_tier);
  expect(content["catalog_version"]).toBe(goldenSelection.request.catalog_version);
  expect(content["source_blob_refs"]).toEqual(fixturePngs.map(sha256));
  const maps = content["control_maps"] as { name: string; kind: string; canny_ref: string; lines_ref: string; preview_ref: string; stats: Record<string, number> }[];
  expect(maps).toHaveLength(3);
  for (let i = 0; i < 3; i++) {
    const g = goldenRender.control_maps[i]!;
    // the golden stores sha256(PNG) where the wire carries base64; the gateway stores the
    // same PNGs by hash — so the refs must be exactly those strings
    expect(maps[i]).toEqual({
      name: g.name, kind: g.kind, canny_ref: g.canny_png_base64, lines_ref: g.lines_png_base64, preview_ref: g.preview_png_base64, stats: g.stats,
    });
    for (const ref of [maps[i]!.canny_ref, maps[i]!.lines_ref, maps[i]!.preview_ref]) {
      const got = await api.getBlob(projectId, ref);
      expect(got.status).toBe(200);
      expect(got.contentType).toBe("image/png");
      expect(sha256(got.bytes)).toBe(ref);
    }
  }
  const prompt = content["prompt"] as GoldenRender["prompt"];
  expect(prompt.template_version).toBe(goldenRender.prompt.template_version);
  expect(prompt.tags_used).toEqual(goldenRender.prompt.tags_used);
  expect(prompt.tags_dropped).toEqual([]);
  expect(prompt.text).toBe(goldenRender.prompt.text); // the fixed template with the tags as DATA (SI-7)
  expect(content["candidates"]).toEqual(goldenRender.candidates);
  expect(content["review_items"]).toEqual(goldenRender.review_items);
  const renders = content["renders"] as { name: string; provider: string; ref: string; status: string; blob_ref: string }[];
  expect(renders.map((r) => [r.name, r.provider, r.status, r.ref])).toEqual(
    VIEWS.map((v) => [v, "mock", "ok", `mock-${renderId}-${v}`]),
  );
  for (const r of renders) {
    const got = await api.getBlob(projectId, r.blob_ref);
    expect(got.status).toBe(200);
    expect(sha256(got.bytes)).toBe(r.blob_ref);
  }
  expect(((await api.composeRender(projectId)).json as { error: string }).error).toBe("render_review_pending");
  expect(((await api.finishSelection(projectId, goldenSelection.request.selection)).json as { error: string }).error).toBe("render_not_approved");

  // ---- render_review approval, then the golden structured selection ----
  await api.approveReview(composedBody.review_id);
  s = await api.state(projectId);
  expect(s.render_review_ready).toBe(true);
  expect(s.render).toMatchObject({ status: "composed", render_review_id: composedBody.review_id, render_review_status: "approved" });
  expect(((await api.composeRender(projectId)).json as { error: string }).error).toBe("render_already_composed");
  // a hostile selection is refused without a card
  const hostile = await api.finishSelection(projectId, {
    rooms: [{ room_id: "R-001", wall_sku: "CHPT-WALL-PAINT-STD_PLACEHOLDER" }],
    doors: [{ id: "D-001", sku: "'; DROP TABLE reviews; --" }],
  });
  expect(hostile.status).toBe(422);
  expect((hostile.json as { error: string; blocking: string[] }).error).toBe("finish_selection_blocked");
  expect((hostile.json as { blocking: string[] }).blocking).toContain("unknown_sku");
  const notAllowed = await api.finishSelection(projectId, { rooms: [], evil: true });
  expect(notAllowed.status).toBe(400);
  expect((await api.listReviewRows(projectId)).filter((r) => r.kind === "finish_commit")).toEqual([]);

  const selected = await api.finishSelection(projectId, goldenSelection.request.selection);
  expect(selected.status, JSON.stringify(selected.json)).toBe(201);
  const selectedBody = selected.json as { review_id: string; status: string; counts: Record<string, number> };
  expect(selectedBody.status).toBe("pending");
  expect(selectedBody.counts).toEqual(goldenSelection.response.diagnostics.counts); // 109 ops, 51 targets, 18 walls, 7 conflicts, 0 blocking
  const finishContent = await api.reviewContent(projectId, selectedBody.review_id);
  const ops = finishContent["ops"] as GoldenSelection["response"]["ops"];
  // the golden was validated against the generator's render ref; ours names this render
  const renderRef = `mock-${renderId}-plan`;
  expect(finishContent["render_ref"]).toBe(renderRef);
  const normalise = (list: GoldenSelection["response"]["ops"]) =>
    list.map((o) => (o.args.param === "CHPT_Render_Ref" ? { ...o, args: { ...o.args, value: "<render_ref>" } } : o));
  expect(normalise(ops)).toEqual(normalise(goldenSelection.response.ops));
  expect(ops.filter((o) => o.args.param === "CHPT_Render_Ref").every((o) => o.args.value === renderRef)).toBe(true);
  expect(finishContent["review_items"]).toEqual(goldenSelection.response.review_items);
  expect(finishContent["catalog_version"]).toBe(goldenSelection.request.catalog_version);
  expect(finishContent["render_review_id"]).toBe(composedBody.review_id);
  expect(((await api.finishSelection(projectId, goldenSelection.request.selection)).json as { error: string }).error).toBe("finish_review_pending");
  expect(((await api.issueFinish(projectId)).json as { error: string }).error).toBe("finish_review_not_approved");

  // ---- Commit #3: the approved ops verbatim, committed by the sim at seq 5 ----
  await api.approveReview(selectedBody.review_id);
  s = await api.state(projectId);
  expect(s.finish_ready).toBe(true);
  expect(s.finish).toMatchObject({ finish_review_id: selectedBody.review_id, status: "approved", envelope_status: null, reissues: 0 });
  const issued = await api.issueFinish(projectId);
  expect(issued.status, JSON.stringify(issued.json)).toBe(202);
  expect((issued.json as { seq: number }).seq).toBe(5);
  const done = await api.waitForState(projectId, (st) => st.finish_done);
  expect(done.last_committed_seq).toBe(5);
  expect(done.finish_ready).toBe(false);
  expect(done.finish).toMatchObject({ status: "approved", envelope_status: "committed", reissues: 1, hard_failed: false });
  expect(done.recent_envelopes.map((e) => [e.seq, e.status])).toEqual([
    [5, "committed"], [4, "committed"], [3, "committed"], [2, "committed"], [1, "committed"],
  ]);
  // the model itself did not change shape: the sim's plan is still the Phase 6 golden
  expect(readFileSync(join(blobDir, "current_plan.svg"), "utf8")).toBe(golden("phase6_2br_mep.svg"));
  // every Phase 7 route is closed now
  expect(((await api.issueFinish(projectId)).json as { error: string }).error).toBe("finish_already_done");
  expect(((await api.finishSelection(projectId, goldenSelection.request.selection)).json as { error: string }).error).toBe("finish_already_done");
  const rows = await api.listReviewRows(projectId);
  const byKind = (kind: string) => rows.filter((r) => r.kind === kind);
  expect(byKind("render_review").map((r) => r.status)).toEqual(["approved"]);
  expect(byKind("finish_commit").map((r) => r.status)).toEqual(["approved"]);
  expect(byKind("render_failure")).toEqual([]);
  expect(byKind("finish_failure")).toEqual([]);

  // ---- blob upload path (the plugin's): hash verified, workstation-only ----
  const doc = Buffer.from('{"exported": "parameters"}');
  const wrong = await api.putBlob(projectId, sha256(Buffer.from("other")), doc, token, "application/octet-stream");
  expect(wrong.status).toBe(422);
  expect((wrong.json as { error: string }).error).toBe("blob_hash_mismatch");
  expect((await api.putBlob(projectId, sha256(doc), doc, SERVICE_TOKEN, "application/octet-stream")).status).toBe(403);
  const ok = await api.putBlob(projectId, sha256(doc), doc, token, "application/octet-stream");
  expect(ok.status).toBe(201);
  expect((await api.getBlob(projectId, sha256(doc))).contentType).toBe("application/json");
  await stopSim();
}, 300_000);
