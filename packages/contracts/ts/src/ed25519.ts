// Ed25519 sign/verify over raw 32-byte keys, kept in one audited place. Node's crypto
// API takes DER-encoded keys; raw keys are wrapped with the fixed RFC 8410 prefixes.
// The gateway signs with the per-project private seed; executors verify with the raw
// public key delivered at enrollment.
import { createPrivateKey, createPublicKey, sign, verify, type KeyObject } from "node:crypto";

const PKCS8_ED25519_PREFIX = Buffer.from("302e020100300506032b657004220420", "hex");
const SPKI_ED25519_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

function privateKeyFromSeedHex(seedHex: string): KeyObject {
  return createPrivateKey({
    key: Buffer.concat([PKCS8_ED25519_PREFIX, Buffer.from(seedHex, "hex")]),
    format: "der",
    type: "pkcs8",
  });
}

function publicKeyFromRawHex(publicKeyHex: string): KeyObject {
  return createPublicKey({
    key: Buffer.concat([SPKI_ED25519_PREFIX, Buffer.from(publicKeyHex, "hex")]),
    format: "der",
    type: "spki",
  });
}

/** Sign a payload string; returns 128 lowercase hex chars. TEST/gateway use only. */
export function ed25519SignHex(payload: string, privateSeedHex: string): string {
  return sign(null, Buffer.from(payload, "utf8"), privateKeyFromSeedHex(privateSeedHex)).toString("hex");
}

/** Verify a 128-hex signature over the payload's UTF-8 bytes with a raw 64-hex public key. */
export function ed25519VerifyHex(payload: string, sigHex: string, publicKeyHex: string): boolean {
  return verify(
    null,
    Buffer.from(payload, "utf8"),
    publicKeyFromRawHex(publicKeyHex),
    Buffer.from(sigHex, "hex"),
  );
}

/** Derive the raw 64-hex public key from a 64-hex private seed (enrollment delivery). */
export function ed25519PublicKeyHexFromSeed(seedHex: string): string {
  const pub = createPublicKey(privateKeyFromSeedHex(seedHex)).export({ format: "der", type: "spki" });
  return Buffer.from(pub.subarray(pub.length - 32)).toString("hex");
}
