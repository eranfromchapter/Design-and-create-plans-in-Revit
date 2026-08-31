// Typed HTTP client for the Lane A scan converter (SCAN_CONVERTER_URL). The
// review payload is zod-parsed at the boundary — the gateway never trusts the
// converter's shape blindly (its layout is re-validated against the contract
// schema before it can become review content).
import { z } from "zod";
import { chapterLayoutSchema } from "@chapter/contracts";

const unitInfoSchema = z.object({
  detected: z.enum(["mm", "inch", "ft", "cm", "m"]),
  insunits: z.number().int(),
  source: z.enum(["insunits", "heuristic", "override"]),
  confirmation_required: z.boolean(),
  bbox_span_raw: z.number(),
  bbox_span_mm: z.number(),
});

export const reviewPayloadSchema = z.object({
  layout: chapterLayoutSchema,
  unit: unitInfoSchema,
  height_assumption_mm: z.number().min(2100).max(6000),
  assumptions: z.array(
    z.object({ field: z.string(), value: z.unknown(), note: z.string().optional() }),
  ),
  flags: z.array(
    z.object({ element_id: z.string().nullable(), flag: z.string(), detail: z.string() }),
  ),
  low_confidence: z.array(
    z.object({ element_id: z.string(), kind: z.string(), confidence: z.number() }),
  ),
  room_labels: z.array(z.object({ text: z.string(), at: z.tuple([z.number(), z.number()]) })),
  counts: z.object({ walls: z.number(), doors: z.number(), windows: z.number() }),
});
export type ReviewPayload = z.infer<typeof reviewPayloadSchema>;

const errorSchema = z.object({ error: z.string(), message: z.string() });

export type ConvertOutcome =
  | { ok: true; reviewPayload: ReviewPayload }
  | { ok: false; error: string; message: string };

export interface ConvertRequest {
  dxf_base64: string;
  project_id: string;
  level_name?: string;
  ceiling_default_mm?: number;
  unit_override?: string;
  cloud_ref?: string;
}

export async function convertScanBundle(
  baseUrl: string,
  req: ConvertRequest,
): Promise<ConvertOutcome> {
  const res = await fetch(new URL("/convert", baseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  const body: unknown = await res.json();
  if (res.status === 422) {
    const parsed = errorSchema.safeParse(body);
    return {
      ok: false,
      error: parsed.success ? parsed.data.error : "converter_error",
      message: parsed.success ? parsed.data.message : JSON.stringify(body),
    };
  }
  if (!res.ok) {
    return { ok: false, error: "converter_error", message: `converter returned ${res.status}` };
  }
  const parsed = z.object({ review_payload: reviewPayloadSchema }).safeParse(body);
  if (!parsed.success) {
    return { ok: false, error: "converter_error", message: `bad converter response: ${parsed.error.message.slice(0, 500)}` };
  }
  return { ok: true, reviewPayload: parsed.data.review_payload };
}
