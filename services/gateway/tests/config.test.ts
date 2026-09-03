import { describe, expect, it } from "vitest";
import { loadConfig } from "../src/config.js";

const BASE = {
  DATABASE_URL: "postgres://chapter:chapter@localhost:5432/revit_agent",
  ENVELOPE_MASTER_KEY: "07".repeat(32),
  SERVICE_TOKEN: "service-token-0123456789",
};

describe("config", () => {
  it("parses actors and defaults", () => {
    const c = loadConfig({ ...BASE, ACTOR_TOKENS: "tok1:eran@hellochapter.com,tok2:pm@hellochapter.com" });
    expect(c.actors.get("tok1")).toBe("eran@hellochapter.com");
    expect(c.autoApprove).toBe(false);
    expect(c.envelopeTtlDefaultS).toBe(600);
  });

  it("AUTO_APPROVE=1 without CI=true refuses to boot (CI-only guard)", () => {
    expect(() => loadConfig({ ...BASE, AUTO_APPROVE: "1" })).toThrow(/CI-only/);
    expect(loadConfig({ ...BASE, AUTO_APPROVE: "1", CI: "true" }).autoApprove).toBe(true);
  });

  it("ALLOW_PLACEHOLDER_SKUS=1 without CI=true refuses to boot (placeholders never ship)", () => {
    expect(loadConfig(BASE).allowPlaceholders).toBe(false);
    expect(() => loadConfig({ ...BASE, ALLOW_PLACEHOLDER_SKUS: "1" })).toThrow(/CI-only/);
    expect(loadConfig({ ...BASE, ALLOW_PLACEHOLDER_SKUS: "1", CI: "true" }).allowPlaceholders).toBe(true);
  });

  it("Phase 7: AIDM_BRIDGE_URL and BLOB_DIR are optional, the URL must be a URL", () => {
    const off = loadConfig(BASE);
    expect(off.aidmBridgeUrl).toBeNull();
    expect(off.blobDir).toBeNull();
    const on = loadConfig({ ...BASE, AIDM_BRIDGE_URL: "http://127.0.0.1:8790", BLOB_DIR: "/tmp/blobs" });
    expect(on.aidmBridgeUrl).toBe("http://127.0.0.1:8790");
    expect(on.blobDir).toBe("/tmp/blobs");
    expect(() => loadConfig({ ...BASE, AIDM_BRIDGE_URL: "not a url" })).toThrow();
  });

  it("rejects a malformed master key", () => {
    expect(() => loadConfig({ ...BASE, ENVELOPE_MASTER_KEY: "short" })).toThrow();
  });
});
