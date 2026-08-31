// WSS transport wiring: upgrade-time bearer auth (workstation tokens), one active
// executor per project, then hand the socket to GatewayCore. Not a Fastify route on
// purpose — the channel needs upgrade auth and per-connection state.
import type { Server, IncomingMessage } from "node:http";
import type { Duplex } from "node:stream";
import { WebSocketServer } from "ws";
import type { Repos } from "../db/repos.js";
import type { GatewayCore } from "../core.js";

export function attachWss(server: Server, repos: Repos, core: GatewayCore): WebSocketServer {
  const wss = new WebSocketServer({ noServer: true });

  server.on("upgrade", (req: IncomingMessage, socket: Duplex, head: Buffer) => {
    void (async () => {
      const url = new URL(req.url ?? "/", "http://localhost");
      if (url.pathname !== "/wss") {
        socket.destroy();
        return;
      }
      const auth = req.headers.authorization;
      const token = auth?.startsWith("Bearer ") ? auth.slice("Bearer ".length) : null;
      const resolved = token ? await repos.resolveWorkstationToken(token) : null;
      if (!resolved) {
        socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
        socket.destroy();
        return;
      }
      if (core.hasExecutor(resolved.projectId)) {
        // One active executor per project (D3): the second connection is refused.
        socket.write("HTTP/1.1 409 Conflict\r\nConnection: close\r\n\r\n");
        socket.destroy();
        return;
      }
      wss.handleUpgrade(req, socket, head, (ws) => {
        core.register({
          ws,
          projectId: resolved.projectId,
          workstationId: resolved.workstationId,
          helloDone: false,
        });
      });
    })().catch(() => socket.destroy());
  });

  return wss;
}
