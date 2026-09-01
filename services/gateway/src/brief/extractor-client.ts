// Typed HTTP client for the Phase 3 brief extractor (BRIEF_EXTRACTOR_URL). The
// returned brief is zod-parsed against the generated contract schema — the
// gateway never stores a brief it hasn't validated.
import { z } from "zod";
import { clientBriefSchema, type ClientBrief } from "@chapter/contracts";

const responseSchema = z.object({
  brief: clientBriefSchema,
  diagnostics: z.object({
    per_session: z.array(z.record(z.string(), z.unknown())),
    injection_hits: z.number(),
    notes: z.array(z.string()),
    contradiction_count: z.number(),
  }),
});
export type ExtractResult = z.infer<typeof responseSchema>;

const errorSchema = z.object({
  error: z.string(),
  message: z.string(),
  raw_outputs: z.array(z.unknown()).optional(),
});

export type ExtractOutcome =
  | { ok: true; brief: ClientBrief; diagnostics: ExtractResult["diagnostics"] }
  | { ok: false; error: string; message: string; rawOutputs: unknown[] };

export interface ExtractRequest {
  project_id: string;
  brief_version: number;
  sessions: { session_id: string; text: string }[];
  client_names?: string[];
  prior_brief?: unknown;
}

export async function extractBrief(
  baseUrl: string,
  req: ExtractRequest,
): Promise<ExtractOutcome> {
  const res = await fetch(new URL("/extract", baseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(req),
  });
  const body: unknown = await res.json();
  if (res.status === 422) {
    const parsed = errorSchema.safeParse(body);
    return {
      ok: false,
      error: parsed.success ? parsed.data.error : "extractor_error",
      message: parsed.success ? parsed.data.message : JSON.stringify(body),
      rawOutputs: parsed.success ? (parsed.data.raw_outputs ?? []) : [],
    };
  }
  if (!res.ok) {
    return {
      ok: false, error: "extractor_error",
      message: `extractor returned ${res.status}`, rawOutputs: [],
    };
  }
  const parsed = responseSchema.safeParse(body);
  if (!parsed.success) {
    return {
      ok: false, error: "extractor_error",
      message: `bad extractor response: ${parsed.error.message.slice(0, 500)}`, rawOutputs: [],
    };
  }
  return { ok: true, brief: parsed.data.brief, diagnostics: parsed.data.diagnostics };
}
