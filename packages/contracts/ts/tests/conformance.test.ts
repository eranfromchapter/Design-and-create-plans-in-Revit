// Cross-language conformance: this exact suite (same manifest) runs in Python and C# too.
import { describe, expect, it } from "vitest";
import manifest from "../../fixtures/conformance/manifest.json" with { type: "json" };
import { verifyEnvelope } from "../src/verify.js";

describe("signing conformance vectors", () => {
  for (const c of manifest.cases) {
    it(c.name, () => {
      const result = verifyEnvelope(
        c.envelope,
        manifest.public_key_hex,
        new Date(c.verify_at),
        c.last_committed_seq,
      );
      expect(result.status).toBe(c.expect);
      if (result.status === "rejected") {
        expect(result.reason).toBe((c as { reason?: string }).reason);
      }
    });
  }
});
