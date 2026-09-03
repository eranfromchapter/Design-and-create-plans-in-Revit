-- Phase 7: export/render jobs and committed finish selections (docs/PHASE7_DESIGN.md §2).
-- A render job is created BEFORE the export_views envelope is dispatched (so a frame can
-- never arrive without a job to land in) and correlates export_ready frames BY ORDER
-- inside that envelope: blob_refs[i] is the ref for views[i]; refs may repeat (identical
-- bytes) and are never deduped. Status: exporting -> exported (every slot filled) ->
-- composed (render_review created); failed on rollback / ack-reject / TTL expiry /
-- supersession by a newer render-views.
CREATE TABLE render_jobs (
  render_id      uuid PRIMARY KEY,
  project_id     uuid NOT NULL REFERENCES projects(id),
  envelope_id    uuid NOT NULL REFERENCES envelopes(envelope_id),
  status         text NOT NULL DEFAULT 'exporting'
                 CHECK (status IN ('exporting', 'exported', 'composed', 'failed')),
  views          jsonb NOT NULL,              -- [{name, kind, px}] exactly as issued
  expected_views integer NOT NULL CHECK (expected_views BETWEEN 1 AND 20),
  blob_refs      jsonb NOT NULL DEFAULT '[]', -- [sha256 hex | null], index = views index
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX render_jobs_project_created ON render_jobs(project_id, created_at DESC);

-- One row per COMMITTED "Commit #3 finishes" envelope: the approved finish_commit review's
-- selection + the set_parameter ops verbatim (Phase 8 reads this for Division 09).
-- Written inside recordCommitResult's transaction; one per (project, review).
CREATE TABLE finish_selections (
  id              uuid PRIMARY KEY,
  project_id      uuid NOT NULL REFERENCES projects(id),
  review_id       uuid NOT NULL REFERENCES reviews(id),
  envelope_id     uuid NOT NULL REFERENCES envelopes(envelope_id),
  catalog_version text NOT NULL,
  selection       jsonb NOT NULL,
  ops             jsonb NOT NULL,
  committed_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, review_id)
);
-- One pending finish_commit per project at a time (every rebuilt selection is a NEW card),
-- and one pending render_review (two overlapping compose-render calls cannot both file a card).
CREATE UNIQUE INDEX reviews_one_pending_finish_commit ON reviews(project_id)
  WHERE kind = 'finish_commit' AND status = 'pending';
CREATE UNIQUE INDEX reviews_one_pending_render_review ON reviews(project_id)
  WHERE kind = 'render_review' AND status = 'pending';
