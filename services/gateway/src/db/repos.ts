// Thin repository layer: hand-written SQL, zod row-parsing at the boundary.
// event_log rows are written in the SAME transaction as the state change they record.
import { createHash, randomUUID } from "node:crypto";
import type pg from "pg";
import { z } from "zod";
import canonicalize from "canonicalize";
import { idMapHash } from "@chapter/contracts";
import { commit0LayoutFromReview } from "../layout/snapshot.js";
import { clashPairsFromErrors, isHardRollback } from "../layout/merge-verify.js";
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
  resolved_at: z.date().nullable(),
  commit_label: z.string().nullable(),
  approval_ref: z.unknown().nullable(),
  // Phase 6: the executor's rollback errors verbatim + the clash pairs parsed from
  // interference errors (authoritative) merged with clash_delta (supplementary)
  clash_pairs: z.unknown().nullable(),
  errors: z.unknown().nullable(),
});
export type EnvelopeRow = z.infer<typeof envelopeRow>;

/** Phase 7 export/render job (migration 0006): blob_refs[i] is the ref for views[i]. */
const renderJobRow = z.object({
  render_id: z.string(),
  project_id: z.string(),
  envelope_id: z.string(),
  status: z.enum(["exporting", "exported", "composed", "failed"]),
  views: z.array(z.object({ name: z.string(), kind: z.enum(["plan", "section", "3d_hidden"]), px: z.number() })),
  expected_views: z.number(),
  blob_refs: z.array(z.string().nullable()),
  created_at: z.date(),
});
export type RenderJobRow = z.infer<typeof renderJobRow>;
export type RenderView = RenderJobRow["views"][number];

const finishSelectionRow = z.object({
  id: z.string(),
  project_id: z.string(),
  review_id: z.string(),
  envelope_id: z.string(),
  catalog_version: z.string(),
  selection: z.unknown(),
  ops: z.unknown(),
  committed_at: z.date(),
});
export type FinishSelectionRow = z.infer<typeof finishSelectionRow>;

export type AttachOutcome =
  | { attached: true; renderId: string; index: number; complete: boolean }
  | { attached: false; reason: "no_exporting_job" | "envelope_not_committed" | "stale_job" | "job_full" | "unknown_view_name" };

export interface ClashPairRow {
  a_id: string;
  b_id: string;
  kind: string;
}

/** The Phase 6 merge chain (PIN-28): the latest approved interior_plan I and the
 *  latest mep_plan M, the commit2_merge reviews built from exactly (I, M) in order,
 *  the newest one and its newest envelope. Iteration state is DERIVED from this,
 *  never stored. */
export interface MergeChain {
  interior: ReviewRow | null;
  mep: ReviewRow | null;
  merges: ReviewRow[];
  latest: ReviewRow | null;
  envelope: EnvelopeRow | null;
  failed: boolean;
  exhausted: boolean;
}

export const MERGE_BUDGET = 3;

export function envelopeClashPairs(e: EnvelopeRow | null): ClashPairRow[] {
  return Array.isArray(e?.clash_pairs) ? (e!.clash_pairs as ClashPairRow[]) : [];
}

export function envelopeHasInterference(e: EnvelopeRow | null): boolean {
  return e !== null && e.status === "rolled_back" && envelopeClashPairs(e).length > 0;
}

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

  /** Highest seq ever ISSUED (any status) — Commit #2 re-issues take a fresh seq
   *  above both this and the last committed seq (PIN-30), so a rolled-back merged
   *  envelope and its rebuilt successor never share a number. */
  async lastIssuedSeq(projectId: string): Promise<number> {
    const res = await this.db.query(
      `SELECT COALESCE(MAX(seq), 0) AS seq FROM envelopes WHERE project_id = $1`,
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
    reissueOf?: string;
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
        ...(e.reissueOf ? { reissue_of: e.reissueOf } : {}),
      });
      await client.query("COMMIT");
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  /** `projectId` (the executor's session project) scopes the update: a workstation can
   *  only resolve its OWN project's envelopes (SI-10, design §5.3). */
  async recordAck(envelopeId: string, accepted: boolean, reason?: string, projectId?: string): Promise<void> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `UPDATE envelopes
           SET status = $2, reject_reason = $3, resolved_at = CASE WHEN $2 = 'ack_rejected' THEN now() END
         WHERE envelope_id = $1 AND status = 'issued' AND ($4::uuid IS NULL OR project_id = $4::uuid)
         RETURNING project_id`,
        [envelopeId, accepted ? "ack_accepted" : "ack_rejected", reason ?? null, projectId ?? null],
      );
      if (res.rowCount) {
        await this.logEvent(client, res.rows[0].project_id, "gateway", "ack", {
          envelope_id: envelopeId,
          accepted,
          reason,
        });
        // Phase 7: a rejected export envelope strands its render job — fail it now
        if (!accepted) await this.failExportJobs(client, envelopeId, "ack_rejected");
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
    projectId?: string; // the executor's session project: scopes the update (SI-10)
  }): Promise<{ projectId: string; seq: number } | null> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `UPDATE envelopes SET status = $2, resolved_at = now()
         WHERE envelope_id = $1 AND status IN ('issued', 'ack_accepted')
           AND ($3::uuid IS NULL OR project_id = $3::uuid)
         RETURNING project_id, seq`,
        [r.envelopeId, r.committed ? "committed" : "rolled_back", r.projectId ?? null],
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
        // Commit #2 completion (Phase 6): freeze the merged furnished layout (meta
        // levels/panel stamped) — the snapshot row IS commit2_done. Branches stay.
        const commit2 = await client.query(
          `SELECT rv.id AS review_id, rv.content
           FROM envelopes e JOIN reviews rv ON rv.id = (e.approval_ref->>'review_id')::uuid
           WHERE e.envelope_id = $1 AND rv.kind = 'commit2_merge'`,
          [r.envelopeId],
        );
        if (commit2.rowCount) {
          const content = commit2.rows[0].content as { layout: unknown; iterations_used?: number };
          await this.insertSnapshot(client, {
            projectId,
            commitLabel: "commit2",
            seq: Number(seq),
            envelopeId: r.envelopeId,
            reviewId: commit2.rows[0].review_id,
            layout: content.layout,
          });
          await this.logEvent(client, projectId, "gateway", "commit2_done", {
            envelope_id: r.envelopeId,
            seq: Number(seq),
            merge_review_id: commit2.rows[0].review_id,
            iterations_used: content.iterations_used ?? 0,
          });
        }
        // Phase 7: an OLDER export whose frames never all arrived can no longer complete
        // (frames follow their own commit_result; a newer envelope just committed) —
        // terminal instead of stuck. This envelope's own job stays exporting.
        const stale = await client.query(
          `UPDATE render_jobs j SET status = 'failed' FROM envelopes e
           WHERE j.envelope_id = e.envelope_id AND j.project_id = $1 AND j.status = 'exporting'
             AND j.envelope_id <> $2 AND e.status = 'committed'
           RETURNING j.render_id, j.envelope_id`,
          [projectId, r.envelopeId],
        );
        for (const row of stale.rows) {
          await this.logEvent(client, projectId, "gateway", "render_export_failed", {
            render_id: row.render_id, envelope_id: row.envelope_id, cause: "frames_lost",
          });
        }
        // Commit #3 finishes (Phase 7): the committed finish envelope records the approved
        // selection + its set_parameter ops verbatim — the row IS finish_done (Phase 8 reads
        // it for Division 09). One row per (project, review).
        const finish = await client.query(
          `SELECT rv.id AS review_id, rv.content
           FROM envelopes e JOIN reviews rv ON rv.id = (e.approval_ref->>'review_id')::uuid
           WHERE e.envelope_id = $1 AND rv.kind = 'finish_commit'`,
          [r.envelopeId],
        );
        if (finish.rowCount) {
          const content = finish.rows[0].content as {
            selection?: unknown; ops?: unknown[]; catalog_version?: string;
          };
          const inserted = await client.query(
            `INSERT INTO finish_selections
               (id, project_id, review_id, envelope_id, catalog_version, selection, ops)
             VALUES ($1, $2, $3, $4, $5, $6, $7)
             ON CONFLICT (project_id, review_id) DO NOTHING RETURNING id`,
            [
              randomUUID(), projectId, finish.rows[0].review_id, r.envelopeId,
              content.catalog_version ?? "unknown",
              JSON.stringify(content.selection ?? {}), JSON.stringify(content.ops ?? []),
            ],
          );
          if (inserted.rowCount) {
            await this.logEvent(client, projectId, "gateway", "finish_done", {
              envelope_id: r.envelopeId,
              seq: Number(seq),
              finish_review_id: finish.rows[0].review_id,
              ops: Array.isArray(content.ops) ? content.ops.length : 0,
            });
          }
        }
      } else {
        // Rolled back: keep the executor's errors verbatim and, when any of them is an
        // interference, the clash pairs parsed from "A~B" — the AUTHORITATIVE Phase B
        // signal (clash_delta only merges into the same column). A hard code on a
        // Commit #2 envelope (not a clash, not a TTL) means the merged plan is wrong for
        // this model → commit2_failure, never auto-approved, never re-issued.
        const pairs = clashPairsFromErrors(r.errors);
        const existing = await client.query(
          `SELECT clash_pairs FROM envelopes WHERE envelope_id = $1`,
          [r.envelopeId],
        );
        const merged = mergeClashPairs(
          Array.isArray(existing.rows[0]?.clash_pairs) ? (existing.rows[0].clash_pairs as ClashPairRow[]) : [],
          pairs,
        );
        await client.query(
          `UPDATE envelopes SET errors = $2, clash_pairs = $3 WHERE envelope_id = $1`,
          [r.envelopeId, JSON.stringify(r.errors), merged.length ? JSON.stringify(merged) : null],
        );
        const merge = await client.query(
          `SELECT rv.id AS review_id, rv.content
           FROM envelopes e JOIN reviews rv ON rv.id = (e.approval_ref->>'review_id')::uuid
           WHERE e.envelope_id = $1 AND rv.kind = 'commit2_merge'`,
          [r.envelopeId],
        );
        if (merge.rowCount && isHardRollback(r.errors)) {
          const content = merge.rows[0].content as {
            interior?: { review_id?: string };
            mep?: { review_id?: string };
          };
          await this.createReviewWith(client, projectId, "commit2_failure", {
            reason: "executor_rejected",
            hard: true,
            envelope_id: r.envelopeId,
            merge_review_id: merge.rows[0].review_id,
            errors: r.errors,
            chain: {
              interior_review_id: content.interior?.review_id ?? null,
              mep_review_id: content.mep?.review_id ?? null,
            },
          }, false);
        }
        // Phase 7: a rolled-back export envelope emits no frames — its job is failed; a
        // hard code on a finish envelope means the selection is wrong for this model →
        // finish_failure {hard}, never auto-approved, never re-issued (transient codes
        // stay re-issuable up to the cap)
        await this.failExportJobs(client, r.envelopeId, "rolled_back");
        const finish = await client.query(
          `SELECT rv.id AS review_id
           FROM envelopes e JOIN reviews rv ON rv.id = (e.approval_ref->>'review_id')::uuid
           WHERE e.envelope_id = $1 AND rv.kind = 'finish_commit'`,
          [r.envelopeId],
        );
        if (finish.rowCount && isHardRollback(r.errors)) {
          await this.createReviewWith(client, projectId, "finish_failure", {
            reason: "executor_rejected",
            hard: true,
            envelope_id: r.envelopeId,
            finish_review_id: finish.rows[0].review_id,
            errors: r.errors,
          }, false);
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

  /** clash_delta from the executor (supplementary to commit_result): merge into the
   *  envelope's pairs, project-scoped so a workstation can only annotate its own
   *  project's envelopes. Returns false for an unknown envelope (event only). */
  async recordClashDelta(projectId: string, envelopeId: string, pairs: ClashPairRow[]): Promise<boolean> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `SELECT clash_pairs FROM envelopes WHERE envelope_id = $1 AND project_id = $2 FOR UPDATE`,
        [envelopeId, projectId],
      );
      if (!res.rowCount) {
        await client.query("ROLLBACK");
        return false;
      }
      const existing = Array.isArray(res.rows[0].clash_pairs) ? (res.rows[0].clash_pairs as ClashPairRow[]) : [];
      const merged = mergeClashPairs(existing, pairs);
      await client.query(`UPDATE envelopes SET clash_pairs = $2 WHERE envelope_id = $1`, [
        envelopeId, merged.length ? JSON.stringify(merged) : null,
      ]);
      await this.logEvent(client, projectId, "gateway", "clash_delta", {
        envelope_id: envelopeId,
        pairs: merged.length,
      });
      await client.query("COMMIT");
      return true;
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  /** The newest envelope issued under a review's approval_ref (any status). */
  async latestEnvelopeForReview(reviewId: string): Promise<EnvelopeRow | null> {
    const res = await this.db.query(
      `SELECT * FROM envelopes WHERE approval_ref->>'review_id' = $1
       ORDER BY issued_at DESC LIMIT 1`,
      [reviewId],
    );
    return res.rowCount ? envelopeRow.parse(res.rows[0]) : null;
  }

  async envelopeCountForReview(reviewId: string): Promise<number> {
    const res = await this.db.query(
      `SELECT count(*)::int AS n FROM envelopes WHERE approval_ref->>'review_id' = $1`,
      [reviewId],
    );
    return res.rows[0].n as number;
  }

  /** The project's in-flight envelope (issued | ack_accepted), if any. */
  async inflightEnvelope(projectId: string): Promise<EnvelopeRow | null> {
    const res = await this.db.query(
      `SELECT * FROM envelopes WHERE project_id = $1 AND status IN ('issued', 'ack_accepted')
       ORDER BY issued_at DESC LIMIT 1`,
      [projectId],
    );
    return res.rowCount ? envelopeRow.parse(res.rows[0]) : null;
  }

  async listReviewsOfKind(projectId: string, kind: string): Promise<ReviewRow[]> {
    const res = await this.db.query(
      `SELECT * FROM reviews WHERE project_id = $1 AND kind = $2 ORDER BY created_at ASC, id ASC`,
      [projectId, kind],
    );
    return res.rows.map((r) => reviewRow.parse(r));
  }

  async pendingReviewOfKind(projectId: string, kind: string): Promise<ReviewRow | null> {
    const res = await this.db.query(
      `SELECT * FROM reviews WHERE project_id = $1 AND kind = $2 AND status = 'pending'
       ORDER BY created_at DESC LIMIT 1`,
      [projectId, kind],
    );
    return res.rowCount ? reviewRow.parse(res.rows[0]) : null;
  }

  /** The Phase 6 merge chain (PIN-28); see MergeChain. */
  async mergeChain(projectId: string): Promise<MergeChain> {
    const interior = await this.latestReviewOfKind(projectId, "interior_plan");
    const mep = await this.latestReviewOfKind(projectId, "mep_plan");
    const empty: MergeChain = {
      interior, mep, merges: [], latest: null, envelope: null, failed: false, exhausted: false,
    };
    if (!interior || !mep) return empty;
    const chainOf = (content: unknown): { i?: string; m?: string } => {
      const c = content as {
        interior?: { review_id?: string }; mep?: { review_id?: string };
        chain?: { interior_review_id?: string; mep_review_id?: string };
      };
      return {
        i: c.interior?.review_id ?? c.chain?.interior_review_id,
        m: c.mep?.review_id ?? c.chain?.mep_review_id,
      };
    };
    const merges = (await this.listReviewsOfKind(projectId, "commit2_merge")).filter((r) => {
      const c = chainOf(r.content);
      return c.i === interior.id && c.m === mep.id;
    });
    const latest = merges.length ? merges[merges.length - 1]! : null;
    const envelope = latest ? await this.latestEnvelopeForReview(latest.id) : null;
    const failed = (await this.listReviewsOfKind(projectId, "commit2_failure")).some((r) => {
      const c = chainOf(r.content);
      return c.i === interior.id && c.m === mep.id && (r.content as { hard?: boolean }).hard === true;
    });
    const used = latest ? ((latest.content as { iterations_used?: number }).iterations_used ?? 0) : 0;
    const exhausted = latest !== null && used >= MERGE_BUDGET && envelopeHasInterference(envelope);
    return { interior, mep, merges, latest, envelope, failed, exhausted };
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
    for (const row of res.rows) {
      await this.failExportJobs(this.db, row.envelope_id as string, "expired");
    }
    return res.rowCount ?? 0;
  }

  /** An issued envelope that was never dispatched (a dispatch precondition failed, or the
   *  executor vanished between insert and send): resolved as expired NOW so the
   *  one-in-flight slot frees; any export job it opened fails with it. */
  async abandonIssuedEnvelope(envelopeId: string, reason: string): Promise<void> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `UPDATE envelopes SET status = 'expired', resolved_at = now(), reject_reason = $2
         WHERE envelope_id = $1 AND status = 'issued' RETURNING project_id`,
        [envelopeId, reason],
      );
      if (res.rowCount) {
        await this.logEvent(client, res.rows[0].project_id, "gateway", "envelope_abandoned", {
          envelope_id: envelopeId, reason,
        });
        await this.failExportJobs(client, envelopeId, reason);
      }
      await client.query("COMMIT");
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  /** Phase 7: fail every exporting job of a project (a frame could not be attached — the
   *  slot order is no longer trustworthy). */
  async failExportingJobs(projectId: string, cause: string): Promise<number> {
    const res = await this.db.query(
      `UPDATE render_jobs SET status = 'failed'
       WHERE project_id = $1 AND status = 'exporting' RETURNING render_id, envelope_id`,
      [projectId],
    );
    for (const row of res.rows) {
      await this.logEvent(this.db, projectId, "gateway", "render_export_failed", {
        render_id: row.render_id, envelope_id: row.envelope_id, cause,
      });
    }
    return res.rowCount ?? 0;
  }

  /** Phase 7: an export envelope that will never commit strands its exporting job. */
  private async failExportJobs(client: pg.PoolClient | Db, envelopeId: string, cause: string): Promise<void> {
    const res = await client.query(
      `UPDATE render_jobs SET status = 'failed'
       WHERE envelope_id = $1 AND status = 'exporting' RETURNING render_id, project_id`,
      [envelopeId],
    );
    for (const row of res.rows) {
      await this.logEvent(client, row.project_id, "gateway", "render_export_failed", {
        render_id: row.render_id, envelope_id: envelopeId, cause,
      });
    }
  }

  // ---- Phase 7: render jobs + finish selections ----------------------------------

  /** Create the job for an export_views envelope BEFORE it is dispatched (so no frame can
   *  arrive without a job). Any stray exporting job of the project is superseded. */
  async createRenderJob(j: {
    renderId: string;
    projectId: string;
    envelopeId: string;
    views: RenderView[];
  }): Promise<RenderJobRow> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const stray = await client.query(
        `UPDATE render_jobs SET status = 'failed'
         WHERE project_id = $1 AND status = 'exporting' RETURNING render_id`,
        [j.projectId],
      );
      for (const row of stray.rows) {
        await this.logEvent(client, j.projectId, "gateway", "render_job_superseded", {
          render_id: row.render_id, by: j.renderId,
        });
      }
      const res = await client.query(
        `INSERT INTO render_jobs (render_id, project_id, envelope_id, views, expected_views, blob_refs)
         VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`,
        [
          j.renderId, j.projectId, j.envelopeId, JSON.stringify(j.views), j.views.length,
          JSON.stringify(j.views.map(() => null)),
        ],
      );
      await this.logEvent(client, j.projectId, "gateway", "render_job_created", {
        render_id: j.renderId, envelope_id: j.envelopeId, views: j.views.map((v) => v.name),
      });
      await client.query("COMMIT");
      return renderJobRow.parse(res.rows[0]);
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  async getEnvelope(envelopeId: string): Promise<EnvelopeRow | null> {
    const res = await this.db.query("SELECT * FROM envelopes WHERE envelope_id = $1", [envelopeId]);
    return res.rowCount ? envelopeRow.parse(res.rows[0]) : null;
  }

  async latestRenderJob(projectId: string): Promise<RenderJobRow | null> {
    const res = await this.db.query(
      `SELECT * FROM render_jobs WHERE project_id = $1 ORDER BY created_at DESC, render_id DESC LIMIT 1`,
      [projectId],
    );
    return res.rowCount ? renderJobRow.parse(res.rows[0]) : null;
  }

  async getRenderJob(renderId: string): Promise<RenderJobRow | null> {
    const res = await this.db.query("SELECT * FROM render_jobs WHERE render_id = $1", [renderId]);
    return res.rowCount ? renderJobRow.parse(res.rows[0]) : null;
  }

  async setRenderJobStatus(renderId: string, status: RenderJobRow["status"]): Promise<void> {
    await this.db.query("UPDATE render_jobs SET status = $2 WHERE render_id = $1", [renderId, status]);
  }

  /** Land one export_ready view frame (P7-01). The project's latest exporting job whose
   *  envelope COMMITTED takes the frame in its next empty slot (or the named slot when the
   *  frame carries a view name). Refs may repeat — identical bytes are legal. The row is
   *  locked so two frames never race for a slot; completion flips the job to `exported`. */
  async attachExportBlob(
    projectId: string,
    blobRef: string,
    hint?: { envelopeId?: string; name?: string },
  ): Promise<AttachOutcome> {
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const res = await client.query(
        `SELECT j.*, e.status AS envelope_status FROM render_jobs j
           JOIN envelopes e ON e.envelope_id = j.envelope_id
         WHERE j.project_id = $1 AND j.status = 'exporting'
           AND ($2::uuid IS NULL OR j.envelope_id = $2::uuid)
         ORDER BY j.created_at DESC LIMIT 1 FOR UPDATE OF j`,
        [projectId, hint?.envelopeId ?? null],
      );
      if (!res.rowCount) {
        await client.query("ROLLBACK");
        return { attached: false, reason: "no_exporting_job" };
      }
      const row = res.rows[0];
      if (row.envelope_status !== "committed") {
        await client.query("ROLLBACK");
        return { attached: false, reason: "envelope_not_committed" };
      }
      const job = renderJobRow.parse(row);
      // frames follow THEIR envelope's commit_result on the same per-session queue, so the
      // project's newest committed envelope is the frame's envelope; a job whose envelope
      // is older can never complete — terminal, and never a slot for someone else's frame
      const latest = await client.query(
        `SELECT envelope_id FROM envelopes WHERE project_id = $1 AND status = 'committed'
         ORDER BY seq DESC LIMIT 1`,
        [projectId],
      );
      if (latest.rows[0]?.envelope_id !== job.envelope_id) {
        await client.query(`UPDATE render_jobs SET status = 'failed' WHERE render_id = $1`, [job.render_id]);
        await this.logEvent(client, projectId, "gateway", "render_export_failed", {
          render_id: job.render_id, envelope_id: job.envelope_id, cause: "frames_lost",
        });
        await client.query("COMMIT");
        return { attached: false, reason: "stale_job" };
      }
      const refs = [...job.blob_refs];
      while (refs.length < job.expected_views) refs.push(null);
      let index: number;
      if (hint?.name !== undefined) {
        index = job.views.findIndex((v) => v.name === hint.name);
        if (index < 0) {
          await client.query("ROLLBACK");
          return { attached: false, reason: "unknown_view_name" };
        }
        if (refs[index] !== null) {
          await client.query("ROLLBACK");
          return { attached: false, reason: "job_full" };
        }
      } else {
        index = refs.findIndex((r) => r === null);
        if (index < 0) {
          await client.query("ROLLBACK");
          return { attached: false, reason: "job_full" };
        }
      }
      refs[index] = blobRef;
      const complete = refs.every((r) => r !== null);
      await client.query(
        `UPDATE render_jobs SET blob_refs = $2, status = $3 WHERE render_id = $1`,
        [job.render_id, JSON.stringify(refs), complete ? "exported" : "exporting"],
      );
      if (complete) {
        await this.logEvent(client, projectId, "gateway", "render_exported", {
          render_id: job.render_id, envelope_id: job.envelope_id, blob_refs: refs,
        });
      }
      await client.query("COMMIT");
      return { attached: true, renderId: job.render_id, index, complete };
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  /** The project's committed finish selection (one per project in v1 = finish_done). */
  async finishSelectionForProject(projectId: string): Promise<FinishSelectionRow | null> {
    const res = await this.db.query(
      `SELECT * FROM finish_selections WHERE project_id = $1 ORDER BY committed_at DESC LIMIT 1`,
      [projectId],
    );
    return res.rowCount ? finishSelectionRow.parse(res.rows[0]) : null;
  }

  async finishSelectionForReview(reviewId: string): Promise<FinishSelectionRow | null> {
    const res = await this.db.query("SELECT * FROM finish_selections WHERE review_id = $1", [reviewId]);
    return res.rowCount ? finishSelectionRow.parse(res.rows[0]) : null;
  }

  /** A hard finish_failure naming this finish_commit review (executor rejection or the
   *  re-issue cap): the review is spent; a NEW selection restarts. */
  async finishHardFailure(projectId: string, finishReviewId: string): Promise<ReviewRow | null> {
    const res = await this.db.query(
      `SELECT * FROM reviews WHERE project_id = $1 AND kind = 'finish_failure'
         AND content->>'finish_review_id' = $2 AND (content->>'hard')::boolean
       ORDER BY created_at DESC LIMIT 1`,
      [projectId, finishReviewId],
    );
    return res.rowCount ? reviewRow.parse(res.rows[0]) : null;
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
    const client = await this.db.connect();
    try {
      await client.query("BEGIN");
      const review = await this.createReviewWith(client, projectId, kind, content, autoApprove);
      await client.query("COMMIT");
      return review;
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  }

  /** Review insert inside the caller's transaction (commit2_failure rides in the
   *  same transaction as the rollback that caused it). */
  async createReviewWith(
    client: pg.PoolClient,
    projectId: string,
    kind: string,
    content: unknown,
    autoApprove: boolean,
  ): Promise<ReviewRow> {
    const id = randomUUID();
    const doc = canonicalize(content);
    if (doc === undefined) throw new Error("uncanonicalizable review content");
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
    return reviewRow.parse(res.rows[0]);
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

  /** The operative brief: the newest version the client actually confirmed
   *  (Phase 5 staleness — interior_plan_ready compares against this). */
  async latestConfirmedBrief(projectId: string): Promise<BriefRow | null> {
    const res = await this.db.query(
      `SELECT * FROM briefs WHERE project_id = $1 AND confirmed_by_client
       ORDER BY brief_version DESC LIMIT 1`,
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

/** Union of clash pairs by (a_id, b_id), first-seen order, clamped to 256. */
export function mergeClashPairs(existing: ClashPairRow[], incoming: ClashPairRow[]): ClashPairRow[] {
  const seen = new Set<string>();
  const out: ClashPairRow[] = [];
  for (const p of [...existing, ...incoming]) {
    const key = `${p.a_id}~${p.b_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ a_id: p.a_id, b_id: p.b_id, kind: p.kind ?? "hard_interference" });
    if (out.length >= 256) break;
  }
  return out;
}
