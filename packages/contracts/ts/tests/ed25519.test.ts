import { describe, expect, it } from "vitest";
import manifest from "../../fixtures/conformance/manifest.json" with { type: "json" };
import idmapCases from "../../fixtures/idmap/hash_cases.json" with { type: "json" };
import { ed25519PublicKeyHexFromSeed, ed25519SignHex, ed25519VerifyHex } from "../src/ed25519.js";
import { idMapHash } from "../src/idmap.js";

describe("ed25519 helpers", () => {
  it("derives the manifest public key from the test seed", () => {
    expect(ed25519PublicKeyHexFromSeed(manifest.private_seed_hex)).toBe(manifest.public_key_hex);
  });

  it("sign→verify round-trips and matches the manifest's valid vector", () => {
    const valid = manifest.cases.find((c) => c.name === "valid")!;
    const sig = ed25519SignHex(valid.envelope.payload, manifest.private_seed_hex);
    expect(sig).toBe(valid.envelope.sig);
    expect(ed25519VerifyHex(valid.envelope.payload, sig, manifest.public_key_hex)).toBe(true);
  });
});

describe("id-map hash", () => {
  for (const c of idmapCases.cases) {
    it(c.name, () => {
      expect(idMapHash(c.entries as Record<string, number>)).toBe(c.expected_hash);
    });
  }
});
