import { z } from "zod";

const envSchema = z.object({
  PORT: z.coerce.number().int().min(0).max(65535).default(8787),
  DATABASE_URL: z.string().min(1),
  // 32-byte hex master key; encrypts per-project Ed25519 seeds at rest (Key Vault in Phase 10).
  ENVELOPE_MASTER_KEY: z.string().regex(/^[0-9a-f]{64}$/),
  // Service-to-service bearer for internal REST (SI-10). Dev-grade; mTLS/VNet in prod.
  SERVICE_TOKEN: z.string().min(16),
  // Human actors for the approvals surface: "token:email,token:email".
  ACTOR_TOKENS: z.string().default(""),
  AUTO_APPROVE: z.enum(["0", "1"]).default("0"),
  // Phase 7: let _PLACEHOLDER SKUs through the bridge validator (goldens/e2e). CI-only,
  // like AUTO_APPROVE — placeholders are never shipped (catalogs/README.md).
  ALLOW_PLACEHOLDER_SKUS: z.enum(["0", "1"]).default("0"),
  CI: z.string().optional(),
  ENVELOPE_TTL_DEFAULT_S: z.coerce.number().int().min(10).max(3600).default(600),
  // Lane A converter base URL (Phase 2); scan routes 503 when unset.
  SCAN_CONVERTER_URL: z.url().optional(),
  // Brief extractor base URL (Phase 3); transcript routes 503 when unset.
  BRIEF_EXTRACTOR_URL: z.url().optional(),
  // Layout compiler base URL (Phase 4); compile-layout routes 503 when unset.
  LAYOUT_COMPILER_URL: z.url().optional(),
  // AIDM bridge base URL (Phase 7); compose-render / finish-selection 503 when unset.
  AIDM_BRIDGE_URL: z.url().optional(),
  // Content-addressed blob root (Phase 7): exports, control maps, renders. Blob routes and
  // compose-render 503 when unset. In e2e this is the sim's --blob-dir (shared FS).
  BLOB_DIR: z.string().min(1).optional(),
});

export interface Config {
  port: number;
  databaseUrl: string;
  masterKey: Buffer;
  serviceToken: string;
  actors: Map<string, string>; // token -> email
  autoApprove: boolean;
  allowPlaceholders: boolean;
  envelopeTtlDefaultS: number;
  scanConverterUrl: string | null;
  briefExtractorUrl: string | null;
  layoutCompilerUrl: string | null;
  aidmBridgeUrl: string | null;
  blobDir: string | null;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const parsed = envSchema.parse(env);

  // AUTO_APPROVE exists ONLY for the CI e2e pipeline (PLAN.md Part I). Refusing to boot
  // outside CI keeps the approval gates real in every other context.
  const autoApprove = parsed.AUTO_APPROVE === "1";
  if (autoApprove && env.CI !== "true") {
    throw new Error("AUTO_APPROVE=1 is CI-only: refusing to boot without CI=true");
  }

  const allowPlaceholders = parsed.ALLOW_PLACEHOLDER_SKUS === "1";
  if (allowPlaceholders && env.CI !== "true") {
    throw new Error("ALLOW_PLACEHOLDER_SKUS=1 is CI-only: refusing to boot without CI=true");
  }

  const actors = new Map<string, string>();
  for (const pair of parsed.ACTOR_TOKENS.split(",").filter(Boolean)) {
    const idx = pair.indexOf(":");
    if (idx < 1 || idx === pair.length - 1) throw new Error("ACTOR_TOKENS must be token:email,...");
    actors.set(pair.slice(0, idx), pair.slice(idx + 1));
  }

  return {
    port: parsed.PORT,
    databaseUrl: parsed.DATABASE_URL,
    masterKey: Buffer.from(parsed.ENVELOPE_MASTER_KEY, "hex"),
    serviceToken: parsed.SERVICE_TOKEN,
    actors,
    autoApprove,
    allowPlaceholders,
    envelopeTtlDefaultS: parsed.ENVELOPE_TTL_DEFAULT_S,
    scanConverterUrl: parsed.SCAN_CONVERTER_URL ?? null,
    briefExtractorUrl: parsed.BRIEF_EXTRACTOR_URL ?? null,
    layoutCompilerUrl: parsed.LAYOUT_COMPILER_URL ?? null,
    aidmBridgeUrl: parsed.AIDM_BRIDGE_URL ?? null,
    blobDir: parsed.BLOB_DIR ?? null,
  };
}
