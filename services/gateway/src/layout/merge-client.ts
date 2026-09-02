// Typed HTTP client for the Phase 6 merge gate (LAYOUT_COMPILER_URL /merge). The
// MergeResult becomes commit2_merge review content after verification
// (merge-verify.ts), so the schema is loose beyond the keys the gateway reads.
// `svgs` is {} unless status == "clean" — never required.
import { z } from "zod";
import { chapterLayoutSchema } from "@chapter/contracts";

export const MERGE_OPS = [
  "place_family",
  "place_device",
  "create_pipe",
  "create_conduit",
  "run_interference_check",
] as const;

const opSchema = z.object({ op: z.enum(MERGE_OPS), args: z.record(z.string(), z.unknown()) });

export const clashPairSchema = z.object({
  a_id: z.string().regex(/^([A-Z]{1,2}-[0-9]{2,4}|revit:[0-9]+)$/),
  b_id: z.string().regex(/^([A-Z]{1,2}-[0-9]{2,4}|revit:[0-9]+)$/),
  kind: z.string().min(1).max(40).default("hard_interference"),
});
export type ClashPair = z.infer<typeof clashPairSchema>;

export const mergeActionSchema = z
  .object({
    iteration: z.number().int(),
    trigger: z.enum(["phase_a", "phase_b"]),
    pair: z.object({ a_id: z.string(), b_id: z.string(), kind: z.string() }),
    lower: z.string(),
    lower_priority: z.number().int(),
    higher: z.string(),
    higher_priority: z.number().int(),
    action: z.enum(["shift_device", "reroute_conduit", "relegalize_furniture", "relocate_stack", "drop", "blocked"]),
    params: z.record(z.string(), z.unknown()),
    changed: z.boolean(),
  })
  .loose();
export type MergeAction = z.infer<typeof mergeActionSchema>;

export const mergeResultSchema = z
  .object({
    status: z.enum(["clean", "budget_exhausted", "blocked"]),
    iteration: z.number().int().min(1),
    iterations_used: z.number().int().min(0),
    interior: z.object({
      review_id: z.string(),
      content_hash: z.string().regex(/^[0-9a-f]{64}$/),
      ops_count: z.number().int(),
      ops_verbatim: z.boolean(),
    }),
    mep: z.object({
      review_id: z.string(),
      content_hash: z.string().regex(/^[0-9a-f]{64}$/),
      ops_count: z.number().int(),
    }),
    layout: chapterLayoutSchema,
    ops: z.array(opSchema).max(1000),
    actions: z.array(mergeActionSchema),
    replan_deltas: z.array(z.record(z.string(), z.unknown())),
    dropped: z.array(z.string()),
    clash_report: z
      .object({
        budget: z.object({ limit: z.number().int(), used: z.number().int(), remaining: z.number().int() }),
        open_clashes: z.array(z.record(z.string(), z.unknown())),
        status: z.string(),
      })
      .loose(),
    svgs: z.record(z.string(), z.string()).default({}),
    blocked_reason: z.string().nullable().default(null),
    counts: z.record(z.string(), z.number()),
  })
  .loose();
export type MergeResult = z.infer<typeof mergeResultSchema>;

const errorSchema = z.object({
  error: z.string(),
  message: z.string(),
  raw_outputs: z.array(z.unknown()).default([]),
});

export type MergeOutcome =
  | { ok: true; result: MergeResult }
  | { ok: false; error: string; message: string; rawOutputs: unknown[] };

export interface MergeBranchRef {
  review_id: string;
  content_hash: string;
  ops?: unknown[];
  layout?: unknown;
  plan?: unknown;
}

export interface MergeRequest {
  project_id: string;
  commit0_layout: unknown;
  commit1_ops: unknown[];
  interior: MergeBranchRef;
  mep: MergeBranchRef;
  iterations_used: number;
  iteration: number;
  prior_actions: unknown[];
  clash_pairs: ClashPair[];
}

export async function mergeCommit2(baseUrl: string, req: MergeRequest): Promise<MergeOutcome> {
  let res: Response;
  let body: unknown;
  try {
    res = await fetch(new URL("/merge", baseUrl), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(req),
    });
    body = await res.json();
  } catch (err) {
    // connection refused / proxy HTML / cut transfer: a TRANSIENT outcome, never a 500
    return { ok: false, error: "layout_compiler_unreachable", message: String(err), rawOutputs: [] };
  }
  if (res.status === 422) {
    const parsed = errorSchema.safeParse(body);
    return {
      ok: false,
      error: parsed.success ? parsed.data.error : "merge_error",
      message: parsed.success ? parsed.data.message : JSON.stringify(body),
      rawOutputs: parsed.success ? parsed.data.raw_outputs : [],
    };
  }
  if (!res.ok) {
    return { ok: false, error: "merge_error", message: `merge returned ${res.status}`, rawOutputs: [] };
  }
  const parsed = mergeResultSchema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false,
      error: "merge_error",
      message: `bad merge response: ${parsed.error.message.slice(0, 500)}`,
      rawOutputs: [],
    };
  }
  return { ok: true, result: parsed.data };
}
