import Fastify, { type FastifyInstance } from "fastify";
import formbody from "@fastify/formbody";
import { ZodError } from "zod";
import type { Config } from "./config.js";
import { createPool, type Db } from "./db/pool.js";
import { migrate } from "./db/migrate.js";
import { Repos } from "./db/repos.js";
import { GatewayCore } from "./core.js";
import { registerRoutes } from "./http/routes.js";
import { attachWss } from "./wss/server.js";
import { FsBlobStore, type BlobStore } from "./blobs/store.js";

export interface Gateway {
  app: FastifyInstance;
  pool: Db;
  repos: Repos;
  core: GatewayCore;
  blobs: BlobStore | null;
}

export async function buildGateway(config: Config, opts?: { logger?: boolean }): Promise<Gateway> {
  const pool = createPool(config.databaseUrl);
  await migrate(pool);

  const app = Fastify({
    logger: opts?.logger === false ? false : { level: process.env["LOG_LEVEL"] ?? "info" },
  });
  // urlencoded parsing for the no-JS review UI forms (confirmation inputs)
  await app.register(formbody);
  // raw bytes for the Phase 7 blob upload (PUT /projects/:id/blobs/:ref): the handler
  // sniffs the type from the bytes and verifies the content hash
  app.addContentTypeParser(
    ["application/octet-stream", "image/png"],
    { parseAs: "buffer" },
    (_req, body, done) => done(null, body),
  );
  // request bodies are zod-parsed inside the handlers: a schema refusal is the
  // caller's error (400 with the issues), never a 500
  app.setErrorHandler((err, _req, reply) => {
    if (err instanceof ZodError) {
      return reply.code(400).send({ error: "bad_request", issues: err.issues.slice(0, 8) });
    }
    return reply.send(err);
  });
  const repos = new Repos(pool);
  const core = new GatewayCore(repos, config, app.log);
  // BLOB_DIR unset: blob routes and compose-render answer 503 (Phase 7 is optional)
  const blobs: BlobStore | null = config.blobDir ? new FsBlobStore(config.blobDir) : null;
  registerRoutes(app, { config, repos, core, blobs });
  await app.ready();
  attachWss(app.server, repos, core);
  return { app, pool, repos, core, blobs };
}
