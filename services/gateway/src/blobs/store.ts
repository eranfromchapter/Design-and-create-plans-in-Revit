// Content-addressed blob store (Phase 7, P7-02). Refs are the lowercase sha256 hex of the
// bytes — 64 chars, inside the wss-messages blobRef charset — so a ref can be verified on
// upload and never needs a lookup table. The filesystem implementation is flat
// (<root>/<ref>), exactly the layout tools/revit-sim writes with --blob-dir, so in CI/e2e
// the sim's blob dir IS the gateway's BLOB_DIR (no upload path needed). Azure Blob lands in
// Phase 10 behind the same interface (with a project prefix).
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, stat, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";

export const BLOB_REF_RE = /^[0-9a-f]{64}$/;

export interface BlobStore {
  /** Store bytes under `ref` (the caller has verified `ref === blobRefFor(bytes)`).
   *  Returns created=false when an identical blob already exists. */
  put(ref: string, bytes: Buffer): Promise<{ created: boolean }>;
  get(ref: string): Promise<Buffer | null>;
  has(ref: string): Promise<boolean>;
}

export function blobRefFor(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

export type BlobType = "png" | "json" | "unknown";

const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/** Type by content, never by a caller-supplied header: PNG magic bytes, or a JSON
 *  document (first non-whitespace byte `{` or `[`). */
export function sniffBlobType(bytes: Buffer): BlobType {
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(PNG_MAGIC)) return "png";
  for (let i = 0; i < Math.min(bytes.length, 64); i++) {
    const b = bytes[i]!;
    if (b === 0x20 || b === 0x09 || b === 0x0a || b === 0x0d) continue;
    return b === 0x7b || b === 0x5b ? "json" : "unknown";
  }
  return "unknown";
}

export function contentTypeFor(kind: BlobType): string {
  return kind === "png" ? "image/png" : kind === "json" ? "application/json" : "application/octet-stream";
}

export class FsBlobStore implements BlobStore {
  constructor(private readonly root: string) {}

  private path(ref: string): string {
    if (!BLOB_REF_RE.test(ref)) throw new Error(`bad blob ref: ${ref}`);
    return join(this.root, ref);
  }

  async put(ref: string, bytes: Buffer): Promise<{ created: boolean }> {
    const target = this.path(ref);
    if (await this.has(ref)) return { created: false };
    await mkdir(this.root, { recursive: true });
    // tmp + rename: a reader never sees a partial blob; a concurrent identical put
    // simply replaces identical bytes
    const tmp = `${target}.${randomUUID()}.tmp`;
    try {
      await writeFile(tmp, bytes);
      await rename(tmp, target);
    } catch (err) {
      await unlink(tmp).catch(() => {});
      throw err;
    }
    return { created: true };
  }

  async get(ref: string): Promise<Buffer | null> {
    try {
      return await readFile(this.path(ref));
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw err;
    }
  }

  async has(ref: string): Promise<boolean> {
    try {
      const s = await stat(this.path(ref));
      return s.isFile();
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return false;
      throw err;
    }
  }
}
