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

function svgFigure(s: string | undefined, caption: string): string {
  if (!s) return "";
  const uri = `data:image/svg+xml;base64,${Buffer.from(s, "utf8").toString("base64")}`;
  return `<figure style="margin:0;flex:1;min-width:0">
      <img src="${uri}" alt="${esc(caption)}" style="width:100%;border:1px solid #ddd">
      <figcaption style="text-align:center">${esc(caption)}</figcaption>
    </figure>`;
}

function countsLine(counts: Record<string, unknown> | undefined): string {
  return Object.entries(counts ?? {})
    .filter(([, v]) => typeof v !== "object")
    .map(([k, v]) => `${esc(k)}: ${esc(String(v))}`)
    .join(" · ");
}

/** mep_plan cards (Phase 6): the furnished branch vs the MEP proposal, the stack
 *  table, every review item (blocking rows highlighted) and — while blocking items
 *  remain — the human-suppliable confirmations form (panel, slab-to-slab) that
 *  re-runs plan-mep. */
function mepPlanCard(r: ReviewRow, projectId: string, tokenQuery: string): string {
  if (r.kind !== "mep_plan") return "";
  const content = r.content as {
    svgs?: { furnished?: string; mep?: string };
    stacks?: { id: string; wall_id: string; offset: number; diameter: number; fixtures?: string[]; snapped?: boolean }[];
    review_items?: { code: string; severity: string; refs?: string[]; message?: string }[];
    counts?: Record<string, unknown>;
    blocking?: string[];
    confirmations?: { panel?: [number, number]; slab_to_slab_mm?: number };
  };
  const stacks = (content.stacks ?? [])
    .map(
      (s) =>
        `<tr><td><code>${esc(s.id)}</code></td><td>${esc(s.wall_id)}</td><td>${esc(String(s.offset))}</td>` +
        `<td>${esc(String(s.diameter))}</td><td>${esc((s.fixtures ?? []).join(", "))}</td>` +
        `<td>${s.snapped ? "snapped" : ""}</td></tr>`,
    )
    .join("");
  const items = (content.review_items ?? [])
    .map(
      (i) =>
        `<tr${i.severity === "blocking" ? ' style="background:#fdd"' : ""}><td>${esc(i.severity)}</td>` +
        `<td><code>${esc(i.code)}</code></td><td>${esc((i.refs ?? []).join(", "))}</td><td>${esc(i.message ?? "")}</td></tr>`,
    )
    .join("");
  const blocking = content.blocking ?? [];
  const panel = content.confirmations?.panel;
  const form =
    blocking.length && r.status === "pending"
      ? `<form method="post" action="/ui/projects/${esc(projectId)}/plan-mep?${tokenQuery}" style="margin:8px 0">
           <strong>Confirm and re-plan</strong> (${blocking.map(esc).join(", ")}):
           panel x <input name="panel_x" type="number" step="0.1" value="${panel ? esc(String(panel[0])) : ""}">
           panel y <input name="panel_y" type="number" step="0.1" value="${panel ? esc(String(panel[1])) : ""}">
           slab-to-slab mm <input name="slab_to_slab_mm" type="number" step="1" value="${esc(String(content.confirmations?.slab_to_slab_mm ?? ""))}">
           <button type="submit">Re-plan MEP</button>
         </form>`
      : "";
  return `<div style="display:flex;gap:12px;margin:8px 0">
      ${svgFigure(content.svgs?.furnished, "Furnished (interior branch)")}
      ${svgFigure(content.svgs?.mep, "MEP proposal (stacks, branches, devices, raceways)")}
    </div>
    <p>${countsLine(content.counts)}</p>
    ${form}
    <details open><summary>Stacks (${(content.stacks ?? []).length})</summary>
      <table border="1" cellpadding="4"><tr><th>id</th><th>wall</th><th>offset</th><th>Ø</th><th>fixtures</th><th></th></tr>${stacks}</table></details>
    <details ${blocking.length ? "open" : ""}><summary>Review items (${(content.review_items ?? []).length}, ${blocking.length} blocking)</summary>
      <table border="1" cellpadding="4"><tr><th>severity</th><th>code</th><th>refs</th><th>message</th></tr>${items}</table></details>`;
}

/** commit2_merge cards (Phase 6): Commit #1 vs the merged Commit #2, the shared
 *  budget, the clash report and every re-plan action — the decision surface for the
 *  merged envelope (each rebuilt plan is a NEW card). */
function commit2MergeCard(r: ReviewRow): string {
  if (r.kind !== "commit2_merge") return "";
  const content = r.content as {
    svgs?: { commit1?: string; merged?: string };
    iteration?: number;
    iterations_used?: number;
    clash_report?: { budget?: { limit: number; used: number; remaining: number }; open_clashes?: unknown[];
      phase_a?: { rounds?: unknown[] }; phase_b?: { replans?: unknown[] }; prisms?: Record<string, number> };
    actions?: { iteration: number; trigger: string; action: string; lower: string; higher: string; changed: boolean }[];
    replan_deltas?: { id: string; kind: string; reason?: string }[];
    dropped?: string[];
    interior?: { ops_verbatim?: boolean };
    counts?: Record<string, unknown>;
  };
  const budget = content.clash_report?.budget;
  const actions = (content.actions ?? [])
    .map(
      (a) =>
        `<tr><td>${esc(String(a.iteration))}</td><td>${esc(a.trigger)}</td><td>${esc(a.action)}</td>` +
        `<td><code>${esc(a.lower)}</code></td><td><code>${esc(a.higher)}</code></td><td>${a.changed ? "yes" : "no"}</td></tr>`,
    )
    .join("");
  const deltas = (content.replan_deltas ?? [])
    .map((d) => `<li><code>${esc(d.id)}</code> (${esc(d.kind)}) — ${esc(d.reason ?? "")}</li>`)
    .join("");
  const verbatim = content.interior?.ops_verbatim
    ? '<span style="background:#dfd;padding:2px 6px">interior ops verbatim</span>'
    : '<span style="background:#fdd;padding:2px 6px">interior ops re-planned</span>';
  return `<div style="display:flex;gap:12px;margin:8px 0">
      ${svgFigure(content.svgs?.commit1, "Commit #1 (approved plan)")}
      ${svgFigure(content.svgs?.merged, "Merged Commit #2 (interior + MEP)")}
    </div>
    <p>iteration ${esc(String(content.iteration ?? "?"))} · budget used ${esc(String(budget?.used ?? content.iterations_used ?? 0))}/${esc(String(budget?.limit ?? 3))} · ${verbatim}</p>
    <p>${countsLine(content.counts)}</p>
    <details open><summary>Clash report — open ${(content.clash_report?.open_clashes ?? []).length}, Phase A rounds ${(content.clash_report?.phase_a?.rounds ?? []).length}, Phase B re-plans ${(content.clash_report?.phase_b?.replans ?? []).length}</summary>
      <p>prisms: ${countsLine(content.clash_report?.prisms)}</p>
      ${actions ? `<table border="1" cellpadding="4"><tr><th>iteration</th><th>trigger</th><th>action</th><th>lower (moved)</th><th>higher</th><th>changed</th></tr>${actions}</table>` : "<p>No re-plans: the branches merged clean.</p>"}
      ${deltas ? `<ul>${deltas}</ul>` : ""}
      ${(content.dropped ?? []).length ? `<p style="color:#b00">Dropped: ${(content.dropped ?? []).map((d) => `<code>${esc(d)}</code>`).join(", ")}</p>` : ""}
    </details>`;
}

function failureBanner(r: ReviewRow): string {
  if (!/_failure$/.test(r.kind)) return "";
  const content = r.content as { reason?: string; error?: string; message?: string; detail?: string; blocked_reason?: string | null };
  const text = [content.reason ?? content.error, content.message ?? content.detail ?? content.blocked_reason]
    .filter((x): x is string => typeof x === "string" && x.length > 0)
    .join(" — ");
  return `<p style="background:#fdd;padding:6px 8px;border-radius:4px"><strong>REVIEW</strong> ${esc(text || r.kind)}</p>`;
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
        ${failureBanner(r)}${layoutCommit1Card(r)}${interiorPlanCard(r)}${mepPlanCard(r, projectId, tokenQuery)}${commit2MergeCard(r)}
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
