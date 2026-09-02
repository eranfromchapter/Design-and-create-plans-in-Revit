// Typed HTTP client for the Phase 6 MEP agent (LAYOUT_COMPILER_URL /plan-mep).
// The MepPlan is stored VERBATIM as mep_plan review content and later handed back to
// /merge as `mep.plan`, so the schema is LOOSE: it pins the keys the gateway reads
// (layout, ops, review_items, blocking, svgs, counts) and keeps every other key.
import { z } from "zod";
import { chapterLayoutSchema } from "@chapter/contracts";

const opSchema = z.object({
  op: z.enum(["create_pipe", "place_device", "create_conduit"]),
  args: z.record(z.string(), z.unknown()),
});

export const mepPlanSchema = z
  .object({
    layout: chapterLayoutSchema,
    ops: z.array(opSchema).max(1000),
    review_items: z.array(
      z
        .object({
          code: z.string().min(1),
          severity: z.enum(["blocking", "info"]),
          refs: z.array(z.string()).default([]),
          message: z.string().default(""),
        })
        .loose(),
    ),
    blocking: z.array(z.string()),
    svgs: z.object({ furnished: z.string().min(1), mep: z.string().min(1) }),
    counts: z
      .object({ devices: z.number().int(), pipes: z.number().int(), stacks: z.number().int(),
        conduits: z.number().int(), blocking: z.number().int() })
      .loose(),
  })
  .loose();
export type MepPlan = z.infer<typeof mepPlanSchema>;

const errorSchema = z.object({
  error: z.string(),
  message: z.string(),
  raw_outputs: z.array(z.unknown()).default([]),
});

export type MepOutcome =
  | { ok: true; plan: MepPlan }
  | { ok: false; error: string; message: string; rawOutputs: unknown[] };

export interface MepConfirmations {
  panel?: [number, number];
  slab_to_slab_mm?: number;
}

export interface MepRequest {
  project_id: string;
  commit0_layout: unknown;
  commit1_layout: unknown;
  commit1_ops: unknown[];
  interior_ops: unknown[];
  furnished_layout: unknown;
  placer_wall_ids: Record<string, string>;
  confirmations: MepConfirmations;
}

export async function planMep(baseUrl: string, req: MepRequest): Promise<MepOutcome> {
  let res: Response;
  let body: unknown;
  try {
    res = await fetch(new URL("/plan-mep", baseUrl), {
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
      error: parsed.success ? parsed.data.error : "mep_error",
      message: parsed.success ? parsed.data.message : JSON.stringify(body),
      rawOutputs: parsed.success ? parsed.data.raw_outputs : [],
    };
  }
  if (!res.ok) {
    return { ok: false, error: "mep_error", message: `plan-mep returned ${res.status}`, rawOutputs: [] };
  }
  const parsed = mepPlanSchema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false,
      error: "mep_error",
      message: `bad plan-mep response: ${parsed.error.message.slice(0, 500)}`,
      rawOutputs: [],
    };
  }
  return { ok: true, plan: parsed.data };
}
