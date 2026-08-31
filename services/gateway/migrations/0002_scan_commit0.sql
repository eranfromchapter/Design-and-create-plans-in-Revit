-- Phase 2 (Lane A): structured approval confirmations on reviews.
-- decision_payload records what the human confirmed alongside the decision
-- (e.g. {"confirmations": {"unit": "mm", "ceiling_height_mm": 2700}}); the
-- reviewed content itself stays immutable (approval_ref hashes content only).
ALTER TABLE reviews ADD COLUMN decision_payload jsonb;
