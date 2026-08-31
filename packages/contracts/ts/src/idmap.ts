// Cross-language id-map hash (hello.id_map_hash, drift gate):
//   sha256( UTF-8( JCS( [[logical_id, element_id], ...] sorted by logical_id ) ) )
// Pinned by packages/contracts/fixtures/idmap/hash_cases.json in TS, Python, and C#.
import { createHash } from "node:crypto";
import canonicalize from "canonicalize";

export function idMapHash(entries: Record<string, number>): string {
  const pairs = Object.keys(entries)
    .sort()
    .map((k) => [k, entries[k]] as [string, number]);
  const doc = canonicalize(pairs);
  if (doc === undefined) throw new Error("uncanonicalizable id map");
  return createHash("sha256").update(doc, "utf8").digest("hex");
}
