// Typed HTTP client for the AIDM bridge (AIDM_BRIDGE_URL): POST /render (control maps +
// prompt + renders + candidates) and POST /finish-selection/validate (the set_parameter
// ops a finish_commit review carries). Same shape as merge-client.ts PLUS request
// deadlines — the render call fronts an external renderer, so the gateway is the first
// caller in the repo that aborts: 150 s for /render (the bridge's own 120 s limit + slack),
// 30 s for the pure validator. Any throw (refused, aborted, cut transfer, non-JSON) is the
// TRANSIENT outcome `aidm_bridge_unreachable`; a 422 is the bridge's verdict (hard).
import { z } from "zod";

export const reviewItemSchema = z
  .object({
    code: z.string().min(1),
    severity: z.enum(["info", "warning", "blocking"]),
    refs: z.array(z.string()).default([]),
    message: z.string().default(""),
  })
  .loose();
export type ReviewItem = z.infer<typeof reviewItemSchema>;

const b64 = z.string().min(1).max(23_000_000); // ~16 MiB decoded, the bridge's own cap

export const controlMapSchema = z.object({
  name: z.string().regex(/^[a-z0-9][a-z0-9_-]{0,63}$/),
  kind: z.enum(["plan", "section", "3d_hidden"]),
  canny_png_base64: b64,
  lines_png_base64: b64,
  preview_png_base64: b64,
  stats: z
    .object({
      edge_px: z.number().int().min(0),
      line_count: z.number().int().min(0),
      width: z.number().int().min(1),
      height: z.number().int().min(1),
    })
    .loose(),
});

export const renderEntrySchema = z
  .object({
    name: z.string().min(1).max(80),
    provider: z.string().min(1).max(40),
    png_base64: b64.nullable().default(null),
    ref: z.string().max(120).nullable().default(null),
    status: z.enum(["ok", "failed", "timeout", "skipped_deadline"]),
    attempts: z.number().int().min(0).default(0),
    error: z.string().nullable().optional(),
  })
  .loose();

export const productSkuSchema = z
  .object({
    sku: z.string().min(1).max(80),
    manufacturer: z.string(),
    model: z.string(),
    description: z.string(),
    finish_tier: z.enum(["economy", "standard", "premium", "luxury"]),
    csi_section: z.string(),
    unit: z.string(),
  })
  .loose();

export const renderResultSchema = z
  .object({
    control_maps: z.array(controlMapSchema).min(1).max(20),
    prompt: z.object({
      template_version: z.string().min(1),
      text: z.string().min(1),
      tags_used: z.array(z.string().max(40)).max(12),
      tags_dropped: z.array(z.object({ tag: z.string().max(200), reason: z.string().max(40) }).loose()).max(64),
    }),
    renders: z.array(renderEntrySchema).max(20),
    candidates: z.record(z.string(), z.array(productSkuSchema).max(500)),
    review_items: z.array(reviewItemSchema).max(500),
    diagnostics: z.record(z.string(), z.unknown()).default({}),
  })
  .loose();
export type RenderResult = z.infer<typeof renderResultSchema>;

/** The exact op shape the gateway will sign — anything else from the bridge is a contract
 *  error, never "close enough". */
export const setParameterOpSchema = z
  .object({
    op: z.literal("set_parameter"),
    args: z
      .object({
        target_id: z.string().min(1).max(40),
        param: z.string().min(1).max(80),
        value: z.union([z.string().max(2000), z.number(), z.boolean()]),
      })
      .strict(),
  })
  .strict();
export type SetParameterOp = z.infer<typeof setParameterOpSchema>;

export const validateResultSchema = z
  .object({
    ops: z.array(setParameterOpSchema).max(1000),
    review_items: z.array(reviewItemSchema).max(2000),
    blocking: z.array(z.string().min(1)).max(64),
    diagnostics: z
      .object({
        per_target: z.record(z.string(), z.unknown()).default({}),
        counts: z.record(z.string(), z.number()).default({}),
      })
      .loose(),
  })
  .loose();
export type ValidateResult = z.infer<typeof validateResultSchema>;

const errorSchema = z.object({
  error: z.string(),
  message: z.string(),
  raw_outputs: z.array(z.unknown()).default([]),
});

export type BridgeOutcome<T> =
  | { ok: true; result: T }
  | { ok: false; error: string; message: string; rawOutputs: unknown[] };

export interface RenderViewIn {
  name: string;
  kind: "plan" | "section" | "3d_hidden";
  px: number;
  png_base64: string;
}

export interface RenderRequest {
  project_id: string;
  render_id: string;
  views: RenderViewIn[];
  style_tags: string[];
  finish_tier: string;
  rooms: { id: string; name: string; program: string }[];
  allow_placeholders: boolean;
}

export interface ValidateRequest {
  project_id: string;
  layout: unknown;
  id_map_ids: string[];
  finish_tier: string;
  catalog_version: string;
  render_ref: string | null;
  selection: unknown;
  allow_placeholders: boolean;
}

export const BRIDGE_TIMEOUTS_DEFAULT = { renderMs: 150_000, validateMs: 30_000 } as const;
let timeouts: { renderMs: number; validateMs: number } = { ...BRIDGE_TIMEOUTS_DEFAULT };

/** Test seam: shrink the deadlines to exercise the abort path. */
export function setBridgeTimeouts(next: Partial<typeof timeouts>): void {
  timeouts = { ...timeouts, ...next };
}

async function post<T>(
  baseUrl: string,
  path: string,
  req: unknown,
  schema: z.ZodType<T>,
  timeoutMs: number,
  fallbackError: string,
): Promise<BridgeOutcome<T>> {
  let res: Response;
  let body: unknown;
  try {
    res = await fetch(new URL(path, baseUrl), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(req),
      signal: AbortSignal.timeout(timeoutMs),
    });
    body = await res.json();
  } catch (err) {
    return { ok: false, error: "aidm_bridge_unreachable", message: String(err), rawOutputs: [] };
  }
  if (res.status === 422) {
    const parsed = errorSchema.safeParse(body);
    return {
      ok: false,
      error: parsed.success ? parsed.data.error : fallbackError,
      message: parsed.success ? parsed.data.message : JSON.stringify(body).slice(0, 2000),
      rawOutputs: parsed.success ? parsed.data.raw_outputs : [],
    };
  }
  if (!res.ok) {
    return { ok: false, error: fallbackError, message: `bridge returned ${res.status}`, rawOutputs: [] };
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false,
      error: fallbackError,
      message: `bad bridge response: ${parsed.error.message.slice(0, 500)}`,
      rawOutputs: [],
    };
  }
  return { ok: true, result: parsed.data };
}

export function renderViews(baseUrl: string, req: RenderRequest): Promise<BridgeOutcome<RenderResult>> {
  return post(baseUrl, "/render", req, renderResultSchema, timeouts.renderMs, "render_error");
}

export function validateSelection(baseUrl: string, req: ValidateRequest): Promise<BridgeOutcome<ValidateResult>> {
  return post(baseUrl, "/finish-selection/validate", req, validateResultSchema, timeouts.validateMs, "finish_validate_error");
}
