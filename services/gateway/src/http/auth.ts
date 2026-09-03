// SI-10: every REST surface authenticates; nothing reaches the signer unauthenticated.
// Dev-grade tokens (service bearer + ACTOR_TOKENS) — mTLS/VNet + HUB identity in prod.
// Phase 7 adds the workstation credential (the enrolled executor's bearer, the same one
// the WSS upgrade checks) for the blob upload path.
import { timingSafeEqual } from "node:crypto";
import type { FastifyReply, FastifyRequest } from "fastify";
import type { Config } from "../config.js";
import type { Repos } from "../db/repos.js";

function bearer(req: FastifyRequest): string | null {
  const h = req.headers.authorization;
  if (!h?.startsWith("Bearer ")) return null;
  return h.slice("Bearer ".length);
}

function tokenEquals(a: string, b: string): boolean {
  const ab = Buffer.from(a, "utf8");
  const bb = Buffer.from(b, "utf8");
  return ab.length === bb.length && timingSafeEqual(ab, bb);
}

/** 401 when no credential; 403 when a credential is present but wrong. */
export function requireService(config: Config) {
  return async (req: FastifyRequest, reply: FastifyReply): Promise<void> => {
    const token = bearer(req);
    if (!token) return reply.code(401).send({ error: "unauthenticated" });
    if (!tokenEquals(token, config.serviceToken)) return reply.code(403).send({ error: "forbidden" });
  };
}

export function resolveActor(config: Config, req: FastifyRequest): string | null {
  const token = bearer(req) ?? (req.query as Record<string, string | undefined>)?.["actor_token"] ?? null;
  if (!token) return null;
  for (const [t, email] of config.actors) if (tokenEquals(token, t)) return email;
  return null;
}

export function requireActor(config: Config) {
  return async (req: FastifyRequest, reply: FastifyReply): Promise<void> => {
    const token = bearer(req) ?? (req.query as Record<string, string | undefined>)?.["actor_token"];
    if (!token) return reply.code(401).send({ error: "unauthenticated" });
    if (!resolveActor(config, req)) return reply.code(403).send({ error: "forbidden" });
  };
}

/** Either credential kind; the actor is tried first so review pages (and the blob
 *  <img> URLs on them) work with `?actor_token=`. */
export function actorOrService(config: Config) {
  const service = requireService(config);
  const actor = requireActor(config);
  return async (req: FastifyRequest, reply: FastifyReply): Promise<void> => {
    if (resolveActor(config, req)) return;
    if (req.headers.authorization) return service(req, reply);
    return actor(req, reply);
  };
}

export interface WorkstationIdentity {
  projectId: string;
  workstationId: string;
}

/** Workstation bearer (the enrolled executor's token; only its hash is stored). Resolves
 *  the identity or sends 401 (no credential) / 403 (unknown or revoked token) and returns
 *  null. The caller still checks the identity's project against the route's `:id`. */
export async function authenticateWorkstation(
  repos: Repos,
  req: FastifyRequest,
  reply: FastifyReply,
): Promise<WorkstationIdentity | null> {
  const token = bearer(req);
  if (!token) {
    await reply.code(401).send({ error: "unauthenticated" });
    return null;
  }
  const resolved = await repos.resolveWorkstationToken(token);
  if (!resolved) {
    await reply.code(403).send({ error: "forbidden" });
    return null;
  }
  return resolved;
}
