// Typed HTTP client for the interior furnish pass (LAYOUT_COMPILER_URL —
// the same service hosts /compile and /furnish). Own zod schema: zod strips
// unknown keys, so reusing the compile schema would silently drop the furnish
// diagnostics the review card and Phase 6 need.
import { z } from "zod";
import { chapterLayoutSchema } from "@chapter/contracts";

const opSchema = z.object({ op: z.literal("place_family"), args: z.record(z.string(), z.unknown()) });

export const furnishResultSchema = z.object({
  layout: chapterLayoutSchema,
  ops: z.array(opSchema),
  svgs: z.object({ commit1: z.string().min(1), furnished: z.string().min(1) }),
  unplaced: z.array(
    z.object({
      item: z.record(z.string(), z.unknown()),
      room_id: z.string(),
      reason: z.string(),
    }),
  ),
  diagnostics: z.object({
    attempts: z.number().int(),
    repair_retried: z.boolean(),
    elapsed_ms: z.number(),
    items: z.array(z.record(z.string(), z.unknown())),
    total_candidates: z.number().int(),
    spiral_total: z.number().int(),
    walls_tried: z.number().int(),
  }),
});
export type FurnishResult = z.infer<typeof furnishResultSchema>;

const errorSchema = z.object({
  error: z.string(),
  message: z.string(),
  raw_outputs: z.array(z.unknown()).default([]),
});

export type FurnishOutcome =
  | { ok: true; result: FurnishResult }
  | { ok: false; error: string; message: string; rawOutputs: unknown[] };

export interface FurnishRequest {
  project_id: string;
  brief: unknown;
  commit0_layout: unknown;
  commit1_layout: unknown;
  commit1_ops: unknown[];
}

export async function furnishLayout(
  baseUrl: string,
  req: FurnishRequest,
): Promise<FurnishOutcome> {
  const res = await fetch(new URL("/furnish", baseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  const body: unknown = await res.json();
  if (res.status === 422) {
    const parsed = errorSchema.safeParse(body);
    return {
      ok: false,
      error: parsed.success ? parsed.data.error : "furnish_error",
      message: parsed.success ? parsed.data.message : JSON.stringify(body),
      rawOutputs: parsed.success ? parsed.data.raw_outputs : [],
    };
  }
  if (!res.ok) {
    return {
      ok: false,
      error: "furnish_error",
      message: `furnish returned ${res.status}`,
      rawOutputs: [],
    };
  }
  const parsed = furnishResultSchema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false,
      error: "furnish_error",
      message: `bad furnish response: ${parsed.error.message.slice(0, 500)}`,
      rawOutputs: [],
    };
  }
  return { ok: true, result: parsed.data };
}
