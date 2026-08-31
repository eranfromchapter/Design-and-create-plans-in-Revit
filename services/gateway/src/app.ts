import Fastify, { type FastifyInstance } from "fastify";
import type { Config } from "./config.js";
import { createPool, type Db } from "./db/pool.js";
import { migrate } from "./db/migrate.js";
import { Repos } from "./db/repos.js";
import { GatewayCore } from "./core.js";
import { registerRoutes } from "./http/routes.js";
import { attachWss } from "./wss/server.js";

export interface Gateway {
  app: FastifyInstance;
  pool: Db;
  repos: Repos;
  core: GatewayCore;
}

export async function buildGateway(config: Config, opts?: { logger?: boolean }): Promise<Gateway> {
  const pool = createPool(config.databaseUrl);
  await migrate(pool);

  const app = Fastify({
    logger: opts?.logger === false ? false : { level: process.env["LOG_LEVEL"] ?? "info" },
  });
  const repos = new Repos(pool);
  const core = new GatewayCore(repos, config, app.log);
  registerRoutes(app, { config, repos, core });
  await app.ready();
  attachWss(app.server, repos, core);
  return { app, pool, repos, core };
}
