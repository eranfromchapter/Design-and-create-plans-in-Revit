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

/** scan_commit0 cards carry the Phase 2 confirmations: ceiling height always,
 *  unit only when the converter had to guess it (heuristic detection). */
function confirmationInputs(r: ReviewRow): string {
  if (r.kind !== "scan_commit0") return "";
  const content = r.content as {
    height_assumption_mm?: number;
    unit?: { detected?: string; confirmation_required?: boolean };
  };
  const ceiling = Number(content?.height_assumption_mm ?? 2700);
  let html = `<label>Ceiling height (mm)
      <input type="number" name="ceiling_height_mm" value="${esc(String(ceiling))}"
             min="2100" max="6000" required>
    </label> `;
  if (content?.unit?.confirmation_required) {
    const detected = String(content.unit.detected ?? "mm");
    const options = ["mm", "inch", "ft", "cm", "m"]
      .map((u) => `<option value="${u}"${u === detected ? " selected" : ""}>${u}</option>`)
      .join("");
    html += `<label>Unit (heuristic — confirm) <select name="unit">${options}</select></label> `;
  }
  // Phase 5 (Q7): confirm structural flags per wall so Part G immutability
  // stops being vacuous on real scans (Lane A never sets these)
  const walls = (r.content as { layout?: { walls?: { id: string }[] } }).layout?.walls ?? [];
  const rows = walls
    .slice(0, 64)
    .map((w) => {
      const boxes = ["is_demising", "is_load_bearing", "is_exterior"]
        .map(
          (flag) =>
            `<label style="margin-right:8px"><input type="checkbox" ` +
            `name="wall_flag.${esc(w.id)}.${flag}"> ${flag.slice(3)}</label>`,
        )
        .join("");
      return `<tr><td><code>${esc(w.id)}</code></td><td>${boxes}</td></tr>`;
    })
    .join("");
  if (rows) {
    html += `<details><summary>Confirm structural wall flags (demising / load-bearing / exterior)</summary>
      <table cellpadding="2">${rows}</table></details>`;
  }
  return html;
}

/** layout_commit1 cards show existing vs new plans side by side plus the
 *  demolition list — the human decision surface for Commit #1. The SVGs are
 *  gateway-assembled compiler output; they still render via data: URIs so the
 *  escape-everything discipline holds. */
function layoutCommit1Card(r: ReviewRow): string {
  if (r.kind !== "layout_commit1") return "";
  const content = r.content as {
    svgs?: { existing?: string; new?: string };
    demolition_list?: { kind: string; id: string }[];
    counts?: Record<string, number>;
  };
  const svg = (s: string | undefined, caption: string): string => {
    if (!s) return "";
    const uri = `data:image/svg+xml;base64,${Buffer.from(s, "utf8").toString("base64")}`;
    return `<figure style="margin:0;flex:1;min-width:0">
        <img src="${uri}" alt="${esc(caption)}" style="width:100%;border:1px solid #ddd">
        <figcaption style="text-align:center">${esc(caption)}</figcaption>
      </figure>`;
  };
  const demolition = (content.demolition_list ?? [])
    .map((d) => `<li><code>${esc(d.id)}</code> (${esc(d.kind)})</li>`)
    .join("");
  const counts = Object.entries(content.counts ?? {})
    .map(([k, v]) => `${esc(k)}: ${esc(String(v))}`)
    .join(" · ");
  return `<div style="display:flex;gap:12px;margin:8px 0">
      ${svg(content.svgs?.existing, "Existing conditions")}
      ${svg(content.svgs?.new, "Proposed plan (demolished dashed)")}
    </div>
    <p>${counts}</p>
    ${demolition ? `<details open><summary>Demolition by phasing (${(content.demolition_list ?? []).length})</summary><ul>${demolition}</ul></details>` : "<p>No demolition.</p>"}`;
}

/** interior_plan cards show Commit #1 vs the furnished plan side by side plus
 *  the unplaced (REVIEW) items — the human decision surface for the interior
 *  branch delta Phase 6 will merge. */
function interiorPlanCard(r: ReviewRow): string {
  if (r.kind !== "interior_plan") return "";
  const content = r.content as {
    svgs?: { commit1?: string; furnished?: string };
    unplaced?: { item?: { id?: string; kind?: string }; room_id: string; reason: string }[];
    counts?: Record<string, number>;
  };
  const svg = (s: string | undefined, caption: string): string => {
    if (!s) return "";
    const uri = `data:image/svg+xml;base64,${Buffer.from(s, "utf8").toString("base64")}`;
    return `<figure style="margin:0;flex:1;min-width:0">
        <img src="${uri}" alt="${esc(caption)}" style="width:100%;border:1px solid #ddd">
        <figcaption style="text-align:center">${esc(caption)}</figcaption>
      </figure>`;
  };
  const unplaced = (content.unplaced ?? [])
    .map(
      (u) =>
        `<tr><td><code>${esc(u.item?.id ?? "?")}</code></td><td>${esc(u.item?.kind ?? "?")}</td>` +
        `<td>${esc(u.room_id)}</td><td>${esc(u.reason)}</td></tr>`,
    )
    .join("");
  const counts = Object.entries(content.counts ?? {})
    .map(([k, v]) => `${esc(k)}: ${esc(String(v))}`)
    .join(" · ");
  return `<div style="display:flex;gap:12px;margin:8px 0">
      ${svg(content.svgs?.commit1, "Commit #1 (approved plan)")}
      ${svg(content.svgs?.furnished, "Furnished proposal")}
    </div>
    <p>${counts}</p>
    ${
      unplaced
        ? `<details open><summary>Unplaced — needs review (${(content.unplaced ?? []).length})</summary>
           <table border="1" cellpadding="4"><tr><th>id</th><th>kind</th><th>room</th><th>reason</th></tr>${unplaced}</table></details>`
        : "<p>Every proposed item placed.</p>"
    }`;
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
               ${confirmationInputs(r)}
               <button type="submit">Approve</button>
             </form>
             <form method="post" action="/ui/reviews/${esc(r.id)}/reject?${tokenQuery}" style="display:inline">
               <button type="submit">Reject</button>
             </form>`
          : `<em>${esc(r.status)} by ${esc(r.decided_by ?? "?")}</em>`;
      return `<section style="border:1px solid #ccc;border-radius:6px;padding:12px;margin:12px 0">
        <strong>${esc(r.kind)}</strong> · <code>${esc(r.id)}</code> · ${esc(r.status)}
        ${layoutCommit1Card(r)}${interiorPlanCard(r)}
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
