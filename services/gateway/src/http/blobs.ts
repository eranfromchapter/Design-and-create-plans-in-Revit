// Phase 7 blob routes (P7-02). PUT is the executor's upload path (workstation bearer —
// the plugin PUTs each exported PNG before emitting export_ready; the sim shares the
// directory instead). The ref IS the sha256 of the bytes: the gateway recomputes it and
// refuses a mismatch, so a blob can never be stored under a name its content does not
// justify. GET serves review-card images (actor token in the query) and service reads;
// the content type comes from the bytes, never from the uploader.
import type { FastifyInstance } from "fastify";
import type { Config } from "../config.js";
import type { Repos } from "../db/repos.js";
import {
  BLOB_REF_RE,
  blobRefFor,
  contentTypeFor,
  sniffBlobType,
  type BlobStore,
} from "../blobs/store.js";
import { actorOrService, authenticateWorkstation } from "./auth.js";

export const BLOB_BODY_LIMIT = 32 * 1024 * 1024;

export function registerBlobRoutes(
  app: FastifyInstance,
  deps: { config: Config; repos: Repos; blobs: BlobStore | null },
): void {
  const { config, repos, blobs } = deps;

  app.put(
    "/projects/:id/blobs/:ref",
    { bodyLimit: BLOB_BODY_LIMIT },
    async (req, reply) => {
      const identity = await authenticateWorkstation(repos, req, reply);
      if (!identity) return reply;
      const { id: projectId, ref } = req.params as { id: string; ref: string };
      if (!blobs) return reply.code(503).send({ error: "blob_store_unavailable" });
      // a workstation may only write into its OWN project (SI-10)
      if (identity.projectId !== projectId) return reply.code(403).send({ error: "forbidden" });
      if (!BLOB_REF_RE.test(ref)) return reply.code(400).send({ error: "bad_blob_ref" });
      const body = req.body;
      if (!Buffer.isBuffer(body) || body.length === 0) {
        return reply.code(415).send({ error: "unsupported_blob_type", detail: "send raw bytes as image/png or application/octet-stream" });
      }
      const kind = sniffBlobType(body);
      if (kind === "unknown") return reply.code(415).send({ error: "unsupported_blob_type" });
      const actual = blobRefFor(body);
      if (actual !== ref) {
        return reply.code(422).send({ error: "blob_hash_mismatch", detail: { expected: ref, actual } });
      }
      const { created } = await blobs.put(ref, body);
      if (created) {
        await repos.logEventDirect(projectId, `workstation:${identity.workstationId}`, "blob_stored", {
          blob_ref: ref, bytes: body.length, type: kind,
        });
      }
      return reply.code(created ? 201 : 200).send({ blob_ref: ref, bytes: body.length, type: kind, created });
    },
  );

  app.get("/projects/:id/blobs/:ref", { preHandler: actorOrService(config) }, async (req, reply) => {
    const { id: projectId, ref } = req.params as { id: string; ref: string };
    if (!BLOB_REF_RE.test(ref)) return reply.code(400).send({ error: "bad_blob_ref" });
    if (!(await repos.getProject(projectId))) return reply.code(404).send({ error: "unknown_project" });
    if (!blobs) return reply.code(503).send({ error: "blob_store_unavailable" });
    const bytes = await blobs.get(ref);
    if (!bytes) return reply.code(404).send({ error: "unknown_blob" });
    return reply
      .type(contentTypeFor(sniffBlobType(bytes)))
      .header("cache-control", "private, max-age=31536000, immutable")
      .header("x-content-type-options", "nosniff")
      .send(bytes);
  });
}
