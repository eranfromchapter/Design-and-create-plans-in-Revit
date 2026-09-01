-- Phase 3: versioned client briefs. Each transcript upload produces the next
-- brief_version; approving its client_brief review flips confirmed_by_client
-- (both on the row and inside content.meta — the layout-compiler reads the
-- content and refuses unconfirmed briefs, PLAN.md Part E Phase 4).
CREATE TABLE briefs (
  id                   uuid PRIMARY KEY,
  project_id           uuid NOT NULL REFERENCES projects(id),
  brief_version        integer NOT NULL,
  content              jsonb NOT NULL,
  confirmed_by_client  boolean NOT NULL DEFAULT false,
  review_id            uuid REFERENCES reviews(id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, brief_version)
);
