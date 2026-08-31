-- Phase 1 schema (PLAN.md Part E Phase 1; design D10 in the phase plan).
-- Semantics live in constraints where possible: one committed seq per project,
-- one in-flight envelope per project.

CREATE TABLE projects (
  id                 uuid PRIMARY KEY,
  name               text NOT NULL,
  signing_public_key char(64) NOT NULL,   -- raw Ed25519 public key, hex; delivered at enrollment
  signing_seed_enc   bytea NOT NULL,      -- iv || tag || AES-256-GCM(seed, ENVELOPE_MASTER_KEY)
  commit0_done       boolean NOT NULL DEFAULT false,
  drift_state        text NOT NULL DEFAULT 'clean' CHECK (drift_state IN ('clean', 'dirty')),
  executor_id_map_hash char(64),          -- last hash reported by the executor (hello / state_divergence)
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE workstations (
  project_id     uuid NOT NULL REFERENCES projects(id),
  workstation_id text NOT NULL,
  token_hash     char(64) NOT NULL,       -- sha256(bearer token); the token itself is returned once
  status         text NOT NULL DEFAULT 'enrolled' CHECK (status IN ('enrolled', 'revoked')),
  last_seen_at   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, workstation_id)
);
CREATE UNIQUE INDEX workstations_token ON workstations(token_hash);

CREATE TABLE envelopes (
  envelope_id    uuid PRIMARY KEY,
  project_id     uuid NOT NULL REFERENCES projects(id),
  workstation_id text NOT NULL,
  seq            integer NOT NULL,
  payload        text NOT NULL,
  sig            char(128) NOT NULL,
  commit_label   text,
  approval_ref   jsonb,
  status         text NOT NULL DEFAULT 'issued'
                 CHECK (status IN ('issued', 'ack_accepted', 'ack_rejected',
                                   'committed', 'rolled_back', 'expired')),
  reject_reason  text,
  issued_at      timestamptz NOT NULL,
  resolved_at    timestamptz
);
-- seq may legitimately be re-issued after a rollback; only committed seqs are unique.
CREATE UNIQUE INDEX envelopes_committed_seq ON envelopes(project_id, seq) WHERE status = 'committed';
-- the gateway keeps at most one envelope in flight per project.
CREATE UNIQUE INDEX envelopes_one_inflight ON envelopes(project_id)
  WHERE status IN ('issued', 'ack_accepted');

CREATE TABLE event_log (
  id         bigserial PRIMARY KEY,
  project_id uuid,
  ts         timestamptz NOT NULL DEFAULT now(),
  actor      text NOT NULL,   -- 'service:<name>' | 'human:<email>' | 'workstation:<id>' | 'gateway'
  kind       text NOT NULL,
  payload    jsonb NOT NULL
);

CREATE TABLE id_map (
  project_id    uuid NOT NULL REFERENCES projects(id),
  logical_id    text NOT NULL,
  element_id    bigint NOT NULL,
  committed_seq integer NOT NULL,
  PRIMARY KEY (project_id, logical_id)
);

CREATE TABLE reviews (
  id            uuid PRIMARY KEY,
  project_id    uuid NOT NULL REFERENCES projects(id),
  kind          text NOT NULL,
  status        text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  content       jsonb NOT NULL,
  content_hash  char(64) NOT NULL,        -- sha256 of JCS(content); feeds approval_ref
  created_at    timestamptz NOT NULL DEFAULT now(),
  decided_at    timestamptz,
  decided_by    text,
  decision_note text
);
