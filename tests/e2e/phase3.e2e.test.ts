// Phase 3 acceptance, end to end: fixture transcripts → real brief-extractor
// (replaying the synthetic recorded LLM fixtures) → gateway stores brief v1 +
// client_brief review → approve → confirmed_by_client lands in both places.
// Two real child processes: extractor (FastAPI) + gateway (tsx). No sim — a
// brief commits nothing to the model; Phase 4 consumes it.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, expect, it } from "vitest";
import { GatewayApi } from "./src/api.js";
import {
  REPO_ROOT, startBriefExtractor, startGateway, stop,
  type ConverterProc, type GatewayProc,
} from "./src/harness.js";

const DATABASE_URL = process.env["DATABASE_URL"] ?? "postgres://chapter:chapter@127.0.0.1:5432/revit_agent";

let extractor: ConverterProc;
let gateway: GatewayProc;
let api: GatewayApi;

beforeAll(async () => {
  extractor = await startBriefExtractor();
  gateway = await startGateway(DATABASE_URL, { BRIEF_EXTRACTOR_URL: extractor.url });
  api = new GatewayApi(gateway.url);
});

afterAll(async () => {
  await stop(gateway.proc);
  await stop(extractor.proc);
});

it("two fixture sessions → brief v1 with contradictions → approve → confirmed", async () => {
  const project = await api.createProject("phase3-brief");
  const transcripts = join(REPO_ROOT, "fixtures", "transcripts");
  const sessions = [
    { session_id: "session1_3br", text: readFileSync(join(transcripts, "session1_3br.txt"), "utf8") },
    { session_id: "session2_4br", text: readFileSync(join(transcripts, "session2_4br.txt"), "utf8") },
  ];

  const uploaded = await api.postTranscripts(project.id, sessions);
  expect(uploaded.brief_version).toBe(1);
  expect(uploaded.status).toBe("pending");
  expect(uploaded.contradiction_count).toBe(2); // bedroom count + finish tier

  const before = await api.getBrief(project.id);
  expect(before.confirmed_by_client).toBe(false);
  // the stored brief IS the committed golden (same recorded extractions)
  const golden = JSON.parse(
    readFileSync(join(REPO_ROOT, "fixtures", "briefs", "2br_golden_brief.json"), "utf8"),
  ) as Record<string, unknown>;
  expect(before.brief).toEqual({
    ...golden,
    meta: { ...(golden["meta"] as object), project_id: project.id },
  });

  const pending = (await api.listReviews(project.id)).find(
    (r) => r.kind === "client_brief" && r.status === "pending",
  );
  expect(pending?.id).toBe(uploaded.review_id);
  await api.approveReview(uploaded.review_id);

  const after = await api.getBrief(project.id);
  expect(after.confirmed_by_client).toBe(true);
  expect((after.brief["meta"] as { confirmed_by_client?: boolean }).confirmed_by_client).toBe(true);
});
