// Commit #0 frozen-layout derivation: the approved scan_commit0 review content
// plus the human-confirmed ceiling height applied to every wall. Shared by the
// issue-commit0 route (op heights) and recordCommitResult (the snapshot row),
// so the frozen snapshot always matches what was actually committed.
import type { ChapterLayout } from "@chapter/contracts";
import type { ReviewPayload } from "../scan/converter-client.js";

export interface Commit0Source {
  content: unknown;
  decision_payload: unknown;
}

export function commit0LayoutFromReview(review: Commit0Source): {
  layout: ChapterLayout;
  ceilingMm: number;
} {
  const content = review.content as ReviewPayload;
  const decision = (review.decision_payload ?? {}) as {
    confirmations?: { ceiling_height_mm?: number };
  };
  // auto-approved (CI) reviews carry no confirmations -> converter defaults apply
  const ceilingMm = decision.confirmations?.ceiling_height_mm ?? content.height_assumption_mm;
  const layout: ChapterLayout = {
    ...content.layout,
    walls: content.layout.walls.map((w) => ({ ...w, height: ceilingMm })),
  };
  return { layout, ceilingMm };
}
