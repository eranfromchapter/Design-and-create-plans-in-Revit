// SI-10: every REST surface authenticates; nothing reaches the signer unauthenticated.
// Dev-grade tokens (service bearer + ACTOR_TOKENS) — mTLS/VNet + HUB identity in prod.
import { timingSafeEqual } from "node:crypto";
import type { FastifyReply, FastifyRequest } from "fastify";
import type { Config } from "../config.js";

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
