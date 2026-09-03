-- Phase 6: Commit #2 recovery state. The clash signal is authoritative from the
-- executor's commit_result (errors[].code == 'interference', pairs parsed from
-- "A~B"); clash_delta is supplementary and merges into the same column. Iteration
-- state is derived from the merge chain (commit2_merge reviews + their envelopes),
-- never stored separately. One pending merged plan per project at a time.
ALTER TABLE envelopes ADD COLUMN clash_pairs jsonb;   -- [{a_id, b_id, kind}] from commit_result ∪ clash_delta, clamped
ALTER TABLE envelopes ADD COLUMN errors jsonb;        -- commit_result.errors verbatim (rolled_back only)
CREATE UNIQUE INDEX reviews_one_pending_commit2_merge ON reviews(project_id)
  WHERE kind = 'commit2_merge' AND status = 'pending';
