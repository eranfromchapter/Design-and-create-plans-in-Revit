// Thin repository layer: hand-written SQL, zod row-parsing at the boundary.
// event_log rows are written in the SAME transaction as the state change they record.
import { createHash, randomUUID } from "node:crypto";
import type pg from "pg";
import { z } from "zod";
import canonicalize from "canonicalize";
import { idMapHash } from "@chapter/contracts";
import { commit0LayoutFromReview } from "../layout/snapshot.js";
import type { Db } from "./pool.js";

export const sha256hex = (s: string | Buffer): string =>
  createHash("sha256").update(s).digest("hex");

const projectRow = z.object({
  id: z.string(),
  name: z.string(),
  signing_public_key: z.string(),
  signing_seed_enc: z.instanceof(Buffer),
  commit0_done: z.boolean(),
  drift_state: z.enum(["clean", "dirty"]),
  executor_id_map_hash: z.string().nullable(),
});
export type ProjectRow = z.infer<typeof projectRow>;

const reviewRow = z.object({
  id: z.string(),
  project_id: z.string(),
  kind: z.string(),
  status: z.enum(["pending", "approved", "rejected"]),
  content: z.unknown(),
  content_hash: z.string(),
  created_at: z.date(),
  decided_at: z.date().nullable(),
  decided_by: z.string().nullable(),
  decision_note: z.string().nullable(),
  decision_payload: z.unknown().nullable(),
});
export type ReviewRow = z.infer<typeof reviewRow>;

const briefRow = z.object({
  id: z.string(),
  project_id: z.string(),
  brief_version: z.number(),
  content: z.unknown(),
  confirmed_by_client: z.boolean(),
  review_id: z.string().nullable(),
  created_at: z.date(),
});
export type BriefRow = z.infer<typeof briefRow>;

const snapshotRow = z.object({
  id: z.string(),
  project_id: z.string(),
  commit_label: z.enum(["commit0", "commit1", "commit2"]),
  seq: z.number(),
  envelope_id: z.string(),
  review_id: z.string(),
  layout: z.unknown(),
  layout_hash: z.string(),
  created_at: z.date(),
});
export type SnapshotRow = z.infer<typeof snapshotRow>;

const envelopeRow = z.object({
  envelope_id: z.string(),
  project_id: z.string(),
  workstation_id: z.string(),
  seq: z.number(),
  payload: z.string(),
  sig: z.string(),
  status: z.enum(["issued", "ack_accepted", "ack_rejected", "committed", "rolled_back", "expired"]),
  reject_reason: z.string().nullable(),
  issued_at: z.date(),
});
export type EnvelopeRow = z.infer<typeof envelopeRow>;

export class Repos {
  constructor(private readonly db: Db) {}

  async logEvent(
    client: pg.PoolClient | Db,
    projectId: string | null,
    actor: string,
    kind: string,
    payload: unknown,
  ): Promise<void> {
    await client.query(
      "INSERT INTO event_log (project_id, actor, kind, payload) VALUES ($1, $2, $3, $4)",
      [projectId, actor, kind, JSON.stringify(payload ?? {})],
    );
  }

  /** Standalone event write (no surrounding transaction). */
  async logEventDirect(projectId: string | null, actor: string, kind: string, payload: unknown): Promise<void> {
    await this.logEvent(this.db, projectId, actor, kind, payload);
  }

  async createProject(name: string, publicKeyHex: string, seedEnc: Buffer): Promise<ProjectRow> {
    const id = randomUUID();
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `INSERT INTO projects (id, name, signing_public_key, signing_seed_enc)
         VALUES ($1, $2, $3, $4) RETURNING *`,
        [id, name, publicKeyHex, seedEnc],
      );
      await this.logEvent(client, id, "service:gateway-api", "project_created", { name });
      await client.query("COMMIT");
      return projectRow.parse(res.rows[0]);
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  async getProject(id: string): Promise<ProjectRow | null> {
    const res = await this.db.query("SELECT * FROM projects WHERE id = $1", [id]);
    return res.rowCount ? projectRow.parse(res.rows[0]) : null;
  }

  /** Enroll a workstation; returns the one-time bearer token (only its hash is stored). */
  async enrollWorkstation(projectId: string, workstationId: string): Promise<string> {
    const token = createHash("sha256")
      .update(randomUUID() + randomUUID())
      .digest("hex");
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        `INSERT INTO workstations (project_id, workstation_id, token_hash) VALUES ($1, $2, $3)`,
        [projectId, workstationId, sha256hex(token)],
      );
      await this.logEvent(client, projectId, "service:gateway-api", "workstation_enrolled", {
        workstation_id: workstationId,
      });
      await client.query("COMMIT");
      return token;
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  async resolveWorkstationToken(
    token: string,
  ): Promise<{ projectId: string; workstationId: string } | null> {
    const res = await this.db.query(
      `SELECT project_id, workstation_id FROM workstations
       WHERE token_hash = $1 AND status = 'enrolled'`,
      [sha256hex(token)],
    );
    if (!res.rowCount) return null;
    return { projectId: res.rows[0].project_id, workstationId: res.rows[0].workstation_id };
  }

  async lastCommittedSeq(projectId: string): Promise<number> {
    const res = await this.db.query(
      `SELECT COALESCE(MAX(seq), 0) AS seq FROM envelopes WHERE project_id = $1 AND status = 'committed'`,
      [projectId],
    );
    return Number(res.rows[0].seq);
  }

  async insertIssuedEnvelope(e: {
    envelopeId: string;
    projectId: string;
    workstationId: string;
    seq: number;
    payload: string;
    sig: string;
    commitLabel?: string;
    approvalRef?: unknown;
    issuedAt: string;
  }): Promise<void> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        `INSERT INTO envelopes
           (envelope_id, project_id, workstation_id, seq, payload, sig, commit_label, approval_ref, issued_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
        [
          e.envelopeId, e.projectId, e.workstationId, e.seq, e.payload, e.sig,
          e.commitLabel ?? null, e.approvalRef ? JSON.stringify(e.approvalRef) : null, e.issuedAt,
        ],
      );
      await this.logEvent(client, e.projectId, "gateway", "envelope_issued", {
        envelope_id: e.envelopeId,
        seq: e.seq,
      });
      await client.query("COMMIT");
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  async recordAck(envelopeId: string, accepted: boolean, reason?: string): Promise<void> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `UPDATE envelopes
           SET status = $2, reject_reason = $3, resolved_at = CASE WHEN $2 = 'ack_rejected' THEN now() END
         WHERE envelope_id = $1 AND status = 'issued' RETURNING project_id`,
        [envelopeId, accepted ? "ack_accepted" : "ack_rejected", reason ?? null],
      );
      if (res.rowCount) {
        await this.logEvent(client, res.rows[0].project_id, "gateway", "ack", {
          envelope_id: envelopeId,
          accepted,
          reason,
        });
      }
      await client.query("COMMIT");
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  /** Apply a commit_result: status flip + id_map delta, atomically with the event row. */
  async recordCommitResult(r: {
    envelopeId: string;
    committed: boolean;
    idMapDelta: { logical_id: string; element_id: number }[];
    errors: unknown[];
  }): Promise<{ projectId: string; seq: number } | null> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `UPDATE envelopes SET status = $2, resolved_at = now()
         WHERE envelope_id = $1 AND status IN ('issued', 'ack_accepted')
         RETURNING project_id, seq`,
        [r.envelopeId, r.committed ? "committed" : "rolled_back"],
      );
      if (!res.rowCount) {
        await client.query("ROLLBACK");
        return null;
      }
      const { project_id: projectId, seq } = res.rows[0];
      if (r.committed) {
        for (const d of r.idMapDelta) {
          await client.query(
            `INSERT INTO id_map (project_id, logical_id, element_id, committed_seq)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (project_id, logical_id) DO UPDATE
               SET element_id = EXCLUDED.element_id, committed_seq = EXCLUDED.committed_seq`,
            [projectId, d.logical_id, d.element_id, seq],
          );
        }
        // Commit #0 completion: a committed envelope whose approval_ref points at a
        // scan_commit0 review flips the project flag, atomically with the result —
        // and freezes the commit0 layout snapshot (Phase 4 diffs against it).
        const commit0 = await client.query(
          `UPDATE projects p SET commit0_done = true
           FROM envelopes e JOIN reviews rv ON rv.id = (e.approval_ref->>'review_id')::uuid
           WHERE e.envelope_id = $1 AND rv.kind = 'scan_commit0'
             AND p.id = e.project_id AND p.commit0_done = false
           RETURNING p.id, rv.id AS review_id, rv.content, rv.decision_payload`,
          [r.envelopeId],
        );
        if (commit0.rowCount) {
          const { layout } = commit0LayoutFromReview(commit0.rows[0]);
          await this.insertSnapshot(client, {
            projectId,
            commitLabel: "commit0",
            seq: Number(seq),
            envelopeId: r.envelopeId,
            reviewId: commit0.rows[0].review_id,
            layout,
          });
          await this.logEvent(client, projectId, "gateway", "commit0_done", {
            envelope_id: r.envelopeId,
            seq: Number(seq),
          });
        }
        // Commit #1 completion: freeze the approved phase="new" layout. The
        // snapshot row IS the commit1_done marker (no separate flag).
        const commit1 = await client.query(
          `SELECT rv.id AS review_id, rv.content
           FROM envelopes e JOIN reviews rv ON rv.id = (e.approval_ref->>'review_id')::uuid
           WHERE e.envelope_id = $1 AND rv.kind = 'layout_commit1'`,
          [r.envelopeId],
        );
        if (commit1.rowCount) {
          const content = commit1.rows[0].content as { layout: unknown };
          await this.insertSnapshot(client, {
            projectId,
            commitLabel: "commit1",
            seq: Number(seq),
            envelopeId: r.envelopeId,
            reviewId: commit1.rows[0].review_id,
            layout: content.layout,
          });
        }
      }
      await this.logEvent(client, projectId, "gateway", "commit_result", {
        envelope_id: r.envelopeId,
        committed: r.committed,
        delta: r.idMapDelta.length,
        errors: r.errors,
      });
      await client.query("COMMIT");
      return { projectId, seq: Number(seq) };
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  /** Freeze a layout snapshot (same transaction as the commit result). Frozen by
   *  construction: ON CONFLICT DO NOTHING — an existing label is never replaced. */
  private async insertSnapshot(
    client: pg.PoolClient,
    s: {
      projectId: string;
      commitLabel: "commit0" | "commit1" | "commit2";
      seq: number;
      envelopeId: string;
      reviewId: string;
      layout: unknown;
    },
  ): Promise<void> {
    const doc = canonicalize(s.layout);
    if (doc === undefined) throw new Error("uncanonicalizable layout snapshot");
    const res = await client.query(
      `INSERT INTO layout_snapshots
         (id, project_id, commit_label, seq, envelope_id, review_id, layout, layout_hash)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       ON CONFLICT (project_id, commit_label) DO NOTHING RETURNING id`,
      [
        randomUUID(), s.projectId, s.commitLabel, s.seq, s.envelopeId, s.reviewId,
        JSON.stringify(s.layout), sha256hex(doc),
      ],
    );
    if (res.rowCount) {
      await this.logEvent(client, s.projectId, "gateway", "layout_snapshot_frozen", {
        commit_label: s.commitLabel,
        seq: s.seq,
        layout_hash: sha256hex(doc),
      });
    }
  }

  async getSnapshot(projectId: string, commitLabel: string): Promise<SnapshotRow | null> {
    const res = await this.db.query(
      "SELECT * FROM layout_snapshots WHERE project_id = $1 AND commit_label = $2",
      [projectId, commitLabel],
    );
    return res.rowCount ? snapshotRow.parse(res.rows[0]) : null;
  }

  async hasSnapshot(projectId: string, commitLabel: string): Promise<boolean> {
    const res = await this.db.query(
      "SELECT 1 FROM layout_snapshots WHERE project_id = $1 AND commit_label = $2",
      [projectId, commitLabel],
    );
    return (res.rowCount ?? 0) > 0;
  }

  async expireStaleEnvelopes(): Promise<number> {
    const res = await this.db.query(
      `WITH stale AS (
         SELECT envelope_id, project_id FROM envelopes
         WHERE status IN ('issued', 'ack_accepted')
           AND now() > issued_at + make_interval(secs =>
             ((payload::jsonb)->>'ttl_s')::int)
       )
       UPDATE envelopes e SET status = 'expired', resolved_at = now()
       FROM stale WHERE e.envelope_id = stale.envelope_id
       RETURNING e.envelope_id`,
    );
    return res.rowCount ?? 0;
  }

  async idMapEntries(projectId: string): Promise<Record<string, number>> {
    const res = await this.db.query(
      "SELECT logical_id, element_id FROM id_map WHERE project_id = $1",
      [projectId],
    );
    return Object.fromEntries(res.rows.map((r) => [r.logical_id, Number(r.element_id)]));
  }

  async gatewayIdMapHash(projectId: string): Promise<string> {
    return idMapHash(await this.idMapEntries(projectId));
  }

  async setExecutorState(
    projectId: string,
    executorHash: string,
    drift: "clean" | "dirty",
  ): Promise<void> {
    await this.db.query(
      "UPDATE projects SET executor_id_map_hash = $2, drift_state = $3 WHERE id = $1",
      [projectId, executorHash, drift],
    );
  }

  async createReview(
    projectId: string,
    kind: string,
    content: unknown,
    autoApprove: boolean,
  ): Promise<ReviewRow> {
    const id = randomUUID();
    const doc = canonicalize(content);
    if (doc === undefined) throw new Error("uncanonicalizable review content");
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `INSERT INTO reviews (id, project_id, kind, content, content_hash, status, decided_at, decided_by)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *`,
        [
          id, projectId, kind, JSON.stringify(content), sha256hex(doc),
          autoApprove ? "approved" : "pending",
          autoApprove ? new Date() : null,
          autoApprove ? "auto:ci" : null,
        ],
      );
      await this.logEvent(client, projectId, autoApprove ? "auto:ci" : "gateway", "review_created", {
        review_id: id,
        kind,
        auto_approved: autoApprove,
      });
      await client.query("COMMIT");
      return reviewRow.parse(res.rows[0]);
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  async listReviews(projectId: string): Promise<ReviewRow[]> {
    const res = await this.db.query(
      "SELECT * FROM reviews WHERE project_id = $1 ORDER BY created_at DESC",
      [projectId],
    );
    return res.rows.map((r) => reviewRow.parse(r));
  }

  async getReview(id: string): Promise<ReviewRow | null> {
    const res = await this.db.query("SELECT * FROM reviews WHERE id = $1", [id]);
    return res.rowCount ? reviewRow.parse(res.rows[0]) : null;
  }

  /** Phase 3: store the next brief version AND its client_brief review atomically
   *  (an orphan review or an unreviewed brief must be unobservable). Returns the
   *  brief row + the review. Auto-approved (CI) reviews confirm immediately. */
  async createBriefWithReview(
    projectId: string,
    content: unknown,
    reviewContent: unknown,
    autoApprove: boolean,
  ): Promise<{ brief: BriefRow; review: ReviewRow }> {
    const briefId = randomUUID();
    const reviewId = randomUUID();
    const doc = canonicalize(reviewContent);
    if (doc === undefined) throw new Error("uncanonicalizable review content");
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const version = await client.query(
        "SELECT COALESCE(MAX(brief_version), 0) + 1 AS v FROM briefs WHERE project_id = $1",
        [projectId],
      );
      const briefVersion = Number(version.rows[0].v);
      const reviewRes = await client.query(
        `INSERT INTO reviews (id, project_id, kind, content, content_hash, status, decided_at, decided_by)
         VALUES ($1, $2, 'client_brief', $3, $4, $5, $6, $7) RETURNING *`,
        [
          reviewId, projectId, JSON.stringify(reviewContent), sha256hex(doc),
          autoApprove ? "approved" : "pending",
          autoApprove ? new Date() : null,
          autoApprove ? "auto:ci" : null,
        ],
      );
      const briefRes = await client.query(
        `INSERT INTO briefs (id, project_id, brief_version, content, confirmed_by_client, review_id)
         VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`,
        [briefId, projectId, briefVersion, JSON.stringify(content), false, reviewId],
      );
      if (autoApprove) {
        await this.confirmBrief(client, reviewId);
      }
      await this.logEvent(client, projectId, autoApprove ? "auto:ci" : "gateway", "brief_created", {
        brief_id: briefId,
        brief_version: briefVersion,
        review_id: reviewId,
        auto_approved: autoApprove,
      });
      await client.query("COMMIT");
      const brief = briefRow.parse(
        autoApprove
          ? (await this.db.query("SELECT * FROM briefs WHERE id = $1", [briefId])).rows[0]
          : briefRes.rows[0],
      );
      return { brief, review: reviewRow.parse(reviewRes.rows[0]) };
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  /** Confirmation = the human approved the client_brief review: flip the row flag
   *  AND stamp meta.confirmed_by_client inside the stored content — the
   *  layout-compiler reads the content and refuses unconfirmed briefs (Phase 4). */
  private async confirmBrief(client: pg.PoolClient, reviewId: string): Promise<void> {
    await client.query(
      `UPDATE briefs SET confirmed_by_client = true,
         content = jsonb_set(content, '{meta,confirmed_by_client}', 'true'::jsonb)
       WHERE review_id = $1`,
      [reviewId],
    );
  }

  async latestBrief(projectId: string): Promise<BriefRow | null> {
    const res = await this.db.query(
      "SELECT * FROM briefs WHERE project_id = $1 ORDER BY brief_version DESC LIMIT 1",
      [projectId],
    );
    return res.rowCount ? briefRow.parse(res.rows[0]) : null;
  }

  /** Most recent review of a kind — a newer pending upload supersedes a stale approval. */
  async latestReviewOfKind(projectId: string, kind: string): Promise<ReviewRow | null> {
    const res = await this.db.query(
      `SELECT * FROM reviews WHERE project_id = $1 AND kind = $2
       ORDER BY created_at DESC LIMIT 1`,
      [projectId, kind],
    );
    return res.rowCount ? reviewRow.parse(res.rows[0]) : null;
  }

  async decideReview(
    id: string,
    approved: boolean,
    decidedBy: string,
    note?: string,
    decisionPayload?: unknown,
  ): Promise<ReviewRow | null> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `UPDATE reviews SET status = $2, decided_at = now(), decided_by = $3, decision_note = $4,
           decision_payload = $5
         WHERE id = $1 AND status = 'pending' RETURNING *`,
        [
          id, approved ? "approved" : "rejected", decidedBy, note ?? null,
          decisionPayload === undefined ? null : JSON.stringify(decisionPayload),
        ],
      );
      if (!res.rowCount) {
        await client.query("ROLLBACK");
        return null;
      }
      const review = reviewRow.parse(res.rows[0]);
      // Approving a drift review = the human accepted the model as truth for now
      // (full element-level resync lands with Phase 2's review cards).
      if (review.kind === "drift" && approved) {
        await client.query("UPDATE projects SET drift_state = 'clean' WHERE id = $1", [
          review.project_id,
        ]);
      }
      // Approving a client_brief review = the client confirmed the brief (Phase 3).
      if (review.kind === "client_brief" && approved) {
        await this.confirmBrief(client, review.id);
      }
      await this.logEvent(client, review.project_id, `human:${decidedBy}`, "review_decided", {
        review_id: id,
        approved,
      });
      await client.query("COMMIT");
      return review;
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  async pendingReviewCount(projectId: string): Promise<number> {
    const res = await this.db.query(
      "SELECT count(*)::int AS n FROM reviews WHERE project_id = $1 AND status = 'pending'",
      [projectId],
    );
    return res.rows[0].n as number;
  }

  async recentEnvelopes(projectId: string, limit = 20): Promise<EnvelopeRow[]> {
    const res = await this.db.query(
      "SELECT * FROM envelopes WHERE project_id = $1 ORDER BY issued_at DESC LIMIT $2",
      [projectId, limit],
    );
    return res.rows.map((r) => envelopeRow.parse(r));
  }
}
