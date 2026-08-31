import { loadConfig } from "./config.js";
import { buildGateway } from "./app.js";

const config = loadConfig();
const { app, repos } = await buildGateway(config);

// TTL sweep: envelopes that were accepted but never resolved expire past issued_at+ttl_s.
const sweep = setInterval(() => {
  void repos.expireStaleEnvelopes().catch(() => {});
}, 30_000);
sweep.unref();

const address = await app.listen({ port: config.port, host: "127.0.0.1" });
// Readiness line consumed by the e2e harness — keep the format stable.
console.log(`LISTENING ${new URL(address).port}`);
