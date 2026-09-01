// Typed HTTP client for the layout compiler (LAYOUT_COMPILER_URL). The compile
// result is zod-parsed at the boundary — the layout is re-validated against the
// contract schema and the ops against the envelope-builder's registry check
// before anything is signed.
import { z } from "zod";
import { chapterLayoutSchema } from "@chapter/contracts";

const opSchema = z.object({ op: z.string().min(1), args: z.record(z.string(), z.unknown()) });

export const compileResultSchema = z.object({
  layout: chapterLayoutSchema,
  ops: z.array(opSchema),
  demolition: z.array(
    z.object({ kind: z.enum(["wall", "door", "window"]), id: z.string().min(1) }),
  ),
  svgs: z.object({ existing: z.string().min(1), new: z.string().min(1) }),
  diagnostics: z.object({ attempts: z.number().int(), repair_retried: z.boolean() }),
});
export type CompileResult = z.infer<typeof compileResultSchema>;

const errorSchema = z.object({
  error: z.string(),
  message: z.string(),
  raw_outputs: z.array(z.unknown()).default([]),
});

export type CompileOutcome =
  | { ok: true; result: CompileResult }
  | { ok: false; error: string; message: string; rawOutputs: unknown[] };

export interface CompileRequest {
  project_id: string;
  brief: unknown;
  existing_layout: unknown;
}

export async function compileLayout(
  baseUrl: string,
  req: CompileRequest,
): Promise<CompileOutcome> {
  const res = await fetch(new URL("/compile", baseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  const body: unknown = await res.json();
  if (res.status === 422) {
    const parsed = errorSchema.safeParse(body);
    return {
      ok: false,
      error: parsed.success ? parsed.data.error : "compiler_error",
      message: parsed.success ? parsed.data.message : JSON.stringify(body),
      rawOutputs: parsed.success ? parsed.data.raw_outputs : [],
    };
  }
  if (!res.ok) {
    return {
      ok: false,
      error: "compiler_error",
      message: `compiler returned ${res.status}`,
      rawOutputs: [],
    };
  }
  const parsed = compileResultSchema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false,
      error: "compiler_error",
      message: `bad compiler response: ${parsed.error.message.slice(0, 500)}`,
      rawOutputs: [],
    };
  }
  return { ok: true, result: parsed.data };
}
