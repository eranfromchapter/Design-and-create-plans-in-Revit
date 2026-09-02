// GatewayCore: executor sessions (one per project), WSS message handling, drift
// bookkeeping. Pure protocol/state logic — transport wiring lives in wss/server.ts.
import type { WebSocket } from "ws";
import { wssMessageSchema } from "@chapter/contracts";
import type { Config } from "./config.js";
import type { Repos } from "./db/repos.js";
import { clashPairSchema } from "./layout/merge-client.js";

export interface ExecutorSession {
  ws: WebSocket;
  projectId: string;
  workstationId: string;
  helloDone: boolean;
  /** Phase 6: frames from one executor are processed in arrival order (a
   *  commit_result and its clash_delta must not race), handlers stay idempotent. */
  queue?: Promise<void>;
}

const CLASH_DELTA_MAX_PAIRS = 256;

type Logger = { info: (o: object, msg: string) => void; warn: (o: object, msg: string) => void };

export class GatewayCore {
  private readonly sessions = new Map<string, ExecutorSession>();

  constructor(
    private readonly repos: Repos,
    private readonly config: Config,
    private readonly log: Logger,
  ) {}

  /** One active executor per project: a second connect is refused at upgrade time. */
  hasExecutor(projectId: string): boolean {
    return this.sessions.has(projectId);
  }

  executorReady(projectId: string): boolean {
    return this.sessions.get(projectId)?.helloDone ?? false;
  }

  workstationFor(projectId: string): string | null {
    return this.sessions.get(projectId)?.workstationId ?? null;
  }

  register(session: ExecutorSession): void {
    this.sessions.set(session.projectId, session);
    session.ws.on("close", () => {
      if (this.sessions.get(session.projectId) === session) this.sessions.delete(session.projectId);
    });
    session.ws.on("message", (data) => {
      const raw = data.toString();
      session.queue = (session.queue ?? Promise.resolve()).then(() =>
        this.onMessage(session, raw).catch((err) => {
          this.log.warn({ err: String(err), project: session.projectId }, "wss message handling failed");
        }),
      );
    });
  }

  sendEnvelope(projectId: string, payload: string, sig: string): boolean {
    const session = this.sessions.get(projectId);
    if (!session?.helloDone) return false;
    session.ws.send(JSON.stringify({ type: "envelope", payload, sig }));
    return true;
  }

  private async onMessage(session: ExecutorSession, raw: string): Promise<void> {
    let msg: { type: string } & Record<string, unknown>;
    try {
      msg = wssMessageSchema.parse(JSON.parse(raw)) as { type: string } & Record<string, unknown>;
    } catch {
      session.ws.send(JSON.stringify({ type: "error", code: "invalid_message", message: "frame failed wss-messages.v1 validation" }));
      return;
    }

    switch (msg.type) {
      case "hello":
        await this.onHello(session, msg as unknown as {
          workstation_id: string; plugin_version: string;
          last_committed_seq: number; id_map_hash: string;
        });
        break;
      case "ack": {
        const m = msg as unknown as { envelope_id: string; status: "accepted" | "rejected"; reason?: string };
        await this.repos.recordAck(m.envelope_id, m.status === "accepted", m.reason);
        break;
      }
      case "commit_result": {
        const m = msg as unknown as {
          envelope_id: string; status: "committed" | "rolled_back";
          id_map_delta: { logical_id: string; element_id: number }[]; errors: unknown[];
        };
        await this.repos.recordCommitResult({
          envelopeId: m.envelope_id,
          committed: m.status === "committed",
          idMapDelta: m.id_map_delta,
          errors: m.errors,
        });
        break;
      }
      case "state_divergence": {
        const m = msg as unknown as { last_valid_seq: number; id_map_hash: string; detail?: string };
        await this.markDrift(session.projectId, m.id_map_hash, {
          source: "state_divergence",
          last_valid_seq: m.last_valid_seq,
          detail: m.detail,
        });
        break;
      }
      case "clash_delta": {
        // supplementary to the commit_result interference errors: merge the pairs
        // into the executor's OWN project's envelope (clamped, ids shape-checked);
        // an unknown envelope is event-only
        const m = msg as unknown as { envelope_id: string; pairs: unknown[] };
        const pairs = m.pairs
          .slice(0, CLASH_DELTA_MAX_PAIRS)
          .map((p) => clashPairSchema.safeParse(p))
          .filter((p) => p.success)
          .map((p) => p.data);
        const applied = await this.repos.recordClashDelta(session.projectId, m.envelope_id, pairs);
        if (!applied) {
          await this.repos.logEventDirect(
            session.projectId, `workstation:${session.workstationId}`, "clash_delta_unknown_envelope",
            { envelope_id: m.envelope_id, pairs: pairs.length },
          );
        }
        break;
      }
      case "progress":
      case "export_ready":
        await this.repos.logEventDirect(
          session.projectId, `workstation:${session.workstationId}`, msg.type, msg,
        );
        break;
      case "busy":
        await this.repos.logEventDirect(
          session.projectId, `workstation:${session.workstationId}`, "busy", msg,
        );
        break;
      default:
        session.ws.send(JSON.stringify({ type: "error", code: "unexpected_type", message: msg.type }));
    }
  }

  private async onHello(
    session: ExecutorSession,
    hello: { workstation_id: string; last_committed_seq: number; id_map_hash: string },
  ): Promise<void> {
    const project = await this.repos.getProject(session.projectId);
    if (!project) {
      session.ws.send(JSON.stringify({ type: "auth_error", reason: "unknown_project" }));
      session.ws.close();
      return;
    }
    const gwSeq = await this.repos.lastCommittedSeq(session.projectId);
    const gwHash = await this.repos.gatewayIdMapHash(session.projectId);
    const inSync = hello.last_committed_seq === gwSeq && hello.id_map_hash === gwHash;

    await this.repos.logEventDirect(
      session.projectId, `workstation:${session.workstationId}`, "hello_resync",
      { reported_seq: hello.last_committed_seq, gateway_seq: gwSeq, in_sync: inSync },
    );

    if (inSync) {
      await this.repos.setExecutorState(session.projectId, hello.id_map_hash, "clean");
    } else {
      await this.markDrift(session.projectId, hello.id_map_hash, {
        source: "hello_resync",
        reported_seq: hello.last_committed_seq,
        gateway_seq: gwSeq,
        gateway_hash: gwHash,
      });
    }

    session.helloDone = true;
    session.ws.send(JSON.stringify({
      type: "auth_ok",
      project_id: session.projectId,
      signing_public_key: project.signing_public_key,
    }));
  }

  /** Drift gate marking. Drift reviews are anomaly reports: NEVER auto-approved, even in
   *  CI (AUTO_APPROVE covers pipeline gates, not divergence). A human clears them.
   *  Ordering matters: the review is created BEFORE the project flips dirty, so any
   *  observer that sees drift_state=dirty also sees a pending review to act on. */
  private async markDrift(projectId: string, executorHash: string, content: object): Promise<void> {
    const pending = (await this.repos.listReviews(projectId)).some(
      (r) => r.kind === "drift" && r.status === "pending",
    );
    if (!pending) {
      await this.repos.createReview(projectId, "drift", { ...content, executor_hash: executorHash }, false);
    }
    await this.repos.setExecutorState(projectId, executorHash, "dirty");
    this.log.warn({ project: projectId }, "model state divergence — project marked dirty");
  }

}
