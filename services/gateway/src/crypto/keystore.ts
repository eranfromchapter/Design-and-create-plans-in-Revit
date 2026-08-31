// Per-project Ed25519 seeds, AES-256-GCM-encrypted at rest with the master key
// (ENVELOPE_MASTER_KEY in dev; Key Vault in Phase 10). Private seeds never leave
// this module unencrypted except to sign.
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { ed25519PublicKeyHexFromSeed, ed25519SignHex } from "@chapter/contracts";

const IV_LEN = 12;
const TAG_LEN = 16;

export function encryptSeed(seed: Buffer, masterKey: Buffer): Buffer {
  const iv = randomBytes(IV_LEN);
  const cipher = createCipheriv("aes-256-gcm", masterKey, iv);
  const ct = Buffer.concat([cipher.update(seed), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), ct]);
}

export function decryptSeed(blob: Buffer, masterKey: Buffer): Buffer {
  const iv = blob.subarray(0, IV_LEN);
  const tag = blob.subarray(IV_LEN, IV_LEN + TAG_LEN);
  const ct = blob.subarray(IV_LEN + TAG_LEN);
  const decipher = createDecipheriv("aes-256-gcm", masterKey, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ct), decipher.final()]);
}

export function newProjectKeypair(masterKey: Buffer): { publicKeyHex: string; seedEnc: Buffer } {
  const seed = randomBytes(32);
  return {
    publicKeyHex: ed25519PublicKeyHexFromSeed(seed.toString("hex")),
    seedEnc: encryptSeed(seed, masterKey),
  };
}

export function signPayload(payload: string, seedEnc: Buffer, masterKey: Buffer): string {
  const seed = decryptSeed(seedEnc, masterKey);
  try {
    return ed25519SignHex(payload, seed.toString("hex"));
  } finally {
    seed.fill(0);
  }
}
