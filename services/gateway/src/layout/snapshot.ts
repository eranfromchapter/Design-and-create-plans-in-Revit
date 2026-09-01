// Commit #0 frozen-layout derivation: the approved scan_commit0 review content
// plus the human confirmations applied — ceiling height on every wall, and
// (Phase 5, Q7) the confirmed structural wall flags. Shared by the
// issue-commit0 route (op args) and recordCommitResult (the snapshot row),
// so the frozen snapshot always matches what was actually committed.
import type { ChapterLayout } from "@chapter/contracts";
import type { ReviewPayload } from "../scan/converter-client.js";

export interface WallFlagConfirmations {
  [wallId: string]: {
    is_demising?: boolean;
    is_load_bearing?: boolean;
    is_exterior?: boolean;
  };
}

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
    confirmations?: { ceiling_height_mm?: number; wall_flags?: WallFlagConfirmations };
  };
  // auto-approved (CI) reviews carry no confirmations -> converter defaults apply
  const ceilingMm = decision.confirmations?.ceiling_height_mm ?? content.height_assumption_mm;
  const wallFlags = decision.confirmations?.wall_flags ?? {};
  const layout: ChapterLayout = {
    ...content.layout,
    walls: content.layout.walls.map((w) => ({
      ...w,
      ...(wallFlags[w.id] ?? {}),
      height: ceilingMm,
    })),
  };
  return { layout, ceilingMm };
}
