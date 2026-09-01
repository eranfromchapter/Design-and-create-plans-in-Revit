-- Phase 4: frozen layout snapshots. One row per commit label, written inside
-- recordCommitResult's transaction when the labeled envelope commits:
--   commit0 = the approved scan_commit0 layout with the confirmed ceiling applied
--   commit1 = the approved layout_commit1 phase="new" layout, verbatim
-- Frozen by construction: UNIQUE(project_id, commit_label) and no UPDATE path
-- exists in the codebase. Phases 5/6 read the commit1 row; the Phase 4 diff
-- reads commit0.
CREATE TABLE layout_snapshots (
  id           uuid PRIMARY KEY,
  project_id   uuid NOT NULL REFERENCES projects(id),
  commit_label text NOT NULL CHECK (commit_label IN ('commit0', 'commit1', 'commit2')),
  seq          integer NOT NULL,
  envelope_id  uuid NOT NULL REFERENCES envelopes(envelope_id),
  review_id    uuid NOT NULL REFERENCES reviews(id),
  layout       jsonb NOT NULL,
  layout_hash  char(64) NOT NULL, -- sha256(JCS(layout))
  created_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, commit_label)
);
