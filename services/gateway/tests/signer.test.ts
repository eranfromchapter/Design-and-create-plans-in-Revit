// Closes the sign→verify loop: a gateway-built envelope must verify under the SAME
// contracts implementation the sim/plugin conformance suites pin, and the keystore's
// at-rest encryption must round-trip.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ed25519PublicKeyHexFromSeed, verifyEnvelope } from "@chapter/contracts";
import { buildEnvelope } from "../src/envelope/builder.js";
import { decryptSeed, encryptSeed, newProjectKeypair, signPayload } from "../src/crypto/keystore.js";

const here = dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(
  readFileSync(join(here, "..", "..", "..", "packages", "contracts", "fixtures", "conformance", "manifest.json"), "utf8"),
) as { public_key_hex: string; private_seed_hex: string; cases: { name: string; envelope: { payload: string; sig: string } }[] };

const MASTER = Buffer.alloc(32, 7);

describe("keystore", () => {
  it("encrypts and decrypts seeds (AES-256-GCM)", () => {
    const seed = Buffer.from(manifest.private_seed_hex, "hex");
    const enc = encryptSeed(seed, MASTER);
    expect(decryptSeed(enc, MASTER).equals(seed)).toBe(true);
    expect(enc.subarray(28).equals(seed)).toBe(false); // actually encrypted
  });

  it("signPayload reproduces the conformance manifest's valid signature", () => {
    const seedEnc = encryptSeed(Buffer.from(manifest.private_seed_hex, "hex"), MASTER);
    const valid = manifest.cases.find((c) => c.name === "valid")!;
    expect(signPayload(valid.envelope.payload, seedEnc, MASTER)).toBe(valid.envelope.sig);
  });

  it("newProjectKeypair derives a matching public key", () => {
    const kp = newProjectKeypair(MASTER);
    const seed = decryptSeed(kp.seedEnc, MASTER);
    expect(ed25519PublicKeyHexFromSeed(seed.toString("hex"))).toBe(kp.publicKeyHex);
  });
});

describe("envelope builder", () => {
  const seedEnc = encryptSeed(Buffer.from(manifest.private_seed_hex, "hex"), MASTER);
  const base = {
    projectId: "6f1c2a3e-9b4d-4c5e-8f70-123456789abc",
    workstationId: "ws-design-01",
    seq: 1,
    ttlS: 600,
    issuedAt: new Date("2026-01-01T00:00:00Z"),
  };

  it("builds an envelope the contracts verifier accepts", () => {
    const built = buildEnvelope(
      { ...base, ops: [{ op: "create_level", args: { name: "L1", elevation: 0 } }] },
      seedEnc,
      MASTER,
    );
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    const result = verifyEnvelope(
      { payload: built.payload, sig: built.sig },
      manifest.public_key_hex,
      new Date("2026-01-01T00:05:00Z"),
      0,
    );
    expect(result.status).toBe("accepted");
  });

  it("rejects an unknown op BEFORE signing", () => {
    const built = buildEnvelope(
      { ...base, ops: [{ op: "drop_all_walls", args: {} }] },
      seedEnc,
      MASTER,
    );
    expect(built).toEqual({ ok: false, error: { index: 0, op: "drop_all_walls", reason: "unknown_op" } });
  });

  it("rejects schema-invalid args BEFORE signing", () => {
    const built = buildEnvelope(
      { ...base, ops: [{ op: "create_level", args: { name: "L1" } }] },
      seedEnc,
      MASTER,
    );
    expect(built.ok).toBe(false);
    if (built.ok) return;
    expect(built.error.reason).toBe("invalid_args");
  });
});
