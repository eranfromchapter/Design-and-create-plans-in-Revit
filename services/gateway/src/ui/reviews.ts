// Minimal server-rendered review surface (Phase 0 gate decision). No client JS;
// approve/reject are plain form POSTs. Everything user-controlled is escaped.
import type { ReviewRow } from "../db/repos.js";

function esc(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderReviewsPage(
  projectName: string,
  projectId: string,
  reviews: ReviewRow[],
  actorToken: string,
): string {
  const tokenQuery = `actor_token=${encodeURIComponent(actorToken)}`;
  const cards = reviews
    .map((r) => {
      const content = esc(JSON.stringify(r.content, null, 2));
      const actions =
        r.status === "pending"
          ? `<form method="post" action="/ui/reviews/${esc(r.id)}/approve?${tokenQuery}" style="display:inline">
               <button type="submit">Approve</button>
             </form>
             <form method="post" action="/ui/reviews/${esc(r.id)}/reject?${tokenQuery}" style="display:inline">
               <button type="submit">Reject</button>
             </form>`
          : `<em>${esc(r.status)} by ${esc(r.decided_by ?? "?")}</em>`;
      return `<section style="border:1px solid #ccc;border-radius:6px;padding:12px;margin:12px 0">
        <strong>${esc(r.kind)}</strong> · <code>${esc(r.id)}</code> · ${esc(r.status)}
        <pre style="background:#f6f6f6;padding:8px;overflow-x:auto">${content}</pre>
        ${actions}
      </section>`;
    })
    .join("\n");

  return `<!doctype html>
<html><head><meta charset="utf-8"><title>Reviews — ${esc(projectName)}</title></head>
<body style="font-family:system-ui,sans-serif;max-width:56rem;margin:2rem auto;padding:0 1rem">
<h1>Reviews — ${esc(projectName)}</h1>
<p><code>${esc(projectId)}</code></p>
${cards || "<p>No reviews.</p>"}
</body></html>`;
}
