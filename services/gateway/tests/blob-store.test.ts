// Content-addressed blob store (Phase 7, P7-02): refs are sha256 hex, the FS layout is
// flat (<root>/<ref>) — exactly what tools/revit-sim writes with --blob-dir — and the
// type comes from the bytes, never from a header.
import { mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { BLOB_REF_RE, FsBlobStore, blobRefFor, contentTypeFor, sniffBlobType } from "../src/blobs/store.js";

const PNG_1x1 = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

describe("blob store", () => {
  let root: string;
  beforeEach(async () => {
    root = await mkdtemp(join(tmpdir(), "chapter-blobs-"));
  });
  afterEach(async () => {
    await rm(root, { recursive: true, force: true });
  });

  it("blobRefFor is the lowercase sha256 hex (known vector) and matches the wire pattern", () => {
    expect(blobRefFor(Buffer.from("abc"))).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(BLOB_REF_RE.test(blobRefFor(PNG_1x1))).toBe(true);
    expect(BLOB_REF_RE.test("BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD")).toBe(false);
    expect(BLOB_REF_RE.test("../etc/passwd")).toBe(false);
  });

  it("sniffs PNG by magic bytes and JSON by first non-whitespace byte; everything else unknown", () => {
    expect(sniffBlobType(PNG_1x1)).toBe("png");
    expect(sniffBlobType(Buffer.from('  \n{"a":1}'))).toBe("json");
    expect(sniffBlobType(Buffer.from("[1,2]"))).toBe("json");
    expect(sniffBlobType(Buffer.from("<svg/>"))).toBe("unknown");
    expect(sniffBlobType(Buffer.alloc(0))).toBe("unknown");
    expect(sniffBlobType(Buffer.from([0x89, 0x50, 0x4e]))).toBe("unknown"); // truncated magic
    expect(contentTypeFor("png")).toBe("image/png");
    expect(contentTypeFor("json")).toBe("application/json");
    expect(contentTypeFor("unknown")).toBe("application/octet-stream");
  });

  it("put/get/has round-trip; a repeat put is not a create; the file is <root>/<ref>", async () => {
    const store = new FsBlobStore(root);
    const ref = blobRefFor(PNG_1x1);
    expect(await store.has(ref)).toBe(false);
    expect(await store.get(ref)).toBeNull();
    expect(await store.put(ref, PNG_1x1)).toEqual({ created: true });
    expect(await store.put(ref, PNG_1x1)).toEqual({ created: false });
    expect(await store.has(ref)).toBe(true);
    expect((await store.get(ref))!.equals(PNG_1x1)).toBe(true);
    // the sim's layout: flat, named by the ref, no tmp leftovers
    expect(await readdir(root)).toEqual([ref]);
  });

  it("refuses to touch the filesystem for a malformed ref", async () => {
    const store = new FsBlobStore(root);
    await expect(store.get("../x")).rejects.toThrow(/bad blob ref/);
    await expect(store.put("not-a-ref", PNG_1x1)).rejects.toThrow(/bad blob ref/);
    await expect(store.has("")).rejects.toThrow(/bad blob ref/);
  });

  it("creates the root lazily on first put", async () => {
    const store = new FsBlobStore(join(root, "nested", "deeper"));
    const ref = blobRefFor(Buffer.from("{}"));
    expect(await store.put(ref, Buffer.from("{}"))).toEqual({ created: true });
    expect(await store.has(ref)).toBe(true);
  });
});
