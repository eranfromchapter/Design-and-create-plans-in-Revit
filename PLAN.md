# Chapter Renovation — Revit AI Design & MEP Orchestration Agent
# BUILD PLAN (PLAN.md) — v1.1

> v1.1 amends the original v1.0 plan with the findings of a pre-build adversarial design review
> (55 accepted findings; see `docs/PLAN_REVIEW.md` for the full record and the `AMENDMENTS (v1.1)`
> section at the end of this file for the change index). The architecture is unchanged; the
> amendments close contract gaps that had to be fixed **before** Phase 0 froze the schemas.
>
> Workflow: execute one phase at a time. Never skip a gate.

---

## PART A — OPERATING RULES FOR CLAUDE CODE

1. **Execute phases strictly in order** (Part E). A phase is done only when its Acceptance checklist passes via `make verify` and the Demo artifact exists. Stop and report at every gate. Phases explicitly marked *parallel-eligible* (Phase 3 alongside 1–2) may be built early, but their gates are still reviewed in numeric order.
2. **Ask the human before:** provisioning any cloud resource, adding secrets, changing a contract schema in `packages/contracts`, adding a new op to the allowlist, or any step requiring a Windows machine with Revit installed.
3. **The Security Invariants in Part F are non-negotiable.** If a task appears to require violating one, stop and flag it instead.
4. **`packages/contracts` is the single source of truth.** TypeScript and Python types are generated from the JSON Schemas there (pinned generator versions); the C# records are hand-maintained in `ChapterHub.Core` but CI-verified against the same shared fixtures and conformance vectors — a C# record drifting from the schema fails CI. Never hand-write a duplicate type in TS or Python. After any schema change: regenerate, rebuild all packages, rerun all tests.
5. **Everything must run without Revit.** `tools/revit-sim` is a headless stand-in that speaks the identical WSS protocol and enforces the identical validation. CI never touches Revit. The C# plugin must *compile and unit-test* in CI (via Revit API NuGet stubs); live execution is a manual step on the human's workstation — but is a **required phase-gate checklist item** at Phases 1, 2, and pre-6 (see Part E), not an optional afterthought.
6. **All geometric solvers are bounded.** Every loop has an explicit iteration cap and a timeout. No unbounded search, ever.
7. Fixtures and tests land in the same PR as the feature. One phase = one branch = one PR. Conventional commits.
8. Units: **all contract coordinates are millimeters** (floats). The plugin converts to Revit internal feet (`mm / 304.8`). The sim stays in mm. Every scoring constant in Part G is stated in these units.

---

## PART B — SYSTEM SUMMARY

Hybrid architecture: a thin **C#/.NET 8 Revit plugin** owns all authoritative model writes (Revit's API is single-threaded and in-process only); a **cloud orchestrator** (extends the HUB by Chapter) owns all AI compute, state, and multi-agent planning. They speak over a persistent, signed, outbound **WSS** channel. The plugin executes only HMAC-signed envelopes containing allowlisted, parameterized operations — LLM output can never become code.

```
 Client Portal / HUB review UI ──REST/WSS──┐
                                           ▼
   ┌───────────────── HUB Gateway  (Node 22 / TypeScript, ws) ─────────────────┐
   │   PostgreSQL 16 (scene graph JSONB, event log, reviews)                    │
   │                                                                            │
   │  scan-converter   brief-extractor   layout-compiler                        │
   │  agents: architectural | interior | mep      merge-gate (clash Phase A)    │
   │  aidm-bridge      spec-compiler                    (Python 3.12 / FastAPI) │
   └───────────────▲──────────────────────────────────────────┬────────────────┘
          signed CommandEnvelopes                    acks / progress / exports
                   │            WSS (TLS)                      │
                   └───────── Revit Plugin (C#/.NET 8) ───── Revit 2025/26
                              — or tools/revit-sim in CI —
```

**Pipeline (per project):**
`Polycam capture → scan-converter → review card (human approves) → Commit #0 (phase="Existing") → brief-extractor (transcripts) → layout-compiler (ChapterLayout JSON) → layout review card (human approves) → Architectural Agent → Commit #1 (frozen) → Interior Agent ∥ MEP Agent → merge-gate (clash Phase A) → Commit #2 (clash Phase B in Revit) → aidm-bridge (renders) → designer finish selection → spec-compiler (CSI MasterFormat doc)`

**Trust and drift.** The gateway is the single author of envelopes; the plugin executes only what verifies (Part F threat model). Because designers work interactively in Revit, the gateway runs a **drift gate** before building any envelope after Commit #0: a `verify_model_state` op confirms every id-mapped element still exists with the expected geometry hash; a mismatch routes the project to REVIEW with a defined resync path (re-import changed elements, or a human "accept model as truth" that rebases the snapshot). The scene graph is never assumed current.

**De-risk note:** Chapter already runs a Revit MCP bridge (AUTOM8LABS) on the design workstation. During Phases 1–4 a thin adapter may replay committed envelopes through that MCP for manual smoke tests — under these constraints: manually invoked, bridge bound to localhost, throwaway copies of models only, never client production files. The C# plugin remains the production target; SI-9 requires the MCP bridge be disabled on production workstations before go-live (Phase 10 runbook item).

---

## PART C — REPOSITORY LAYOUT (created in Phase 0)

```
chapter-revit-agent/
├── CLAUDE.md                      # Claude Code operating guide
├── PLAN.md                        # this file
├── Makefile                       # verify, test, codegen, dev-up targets
├── docker-compose.yml             # postgres, gateway, services, revit-sim
├── docs/
│   ├── PLAN_REVIEW.md             # v1.0 design-review record (findings + decisions)
│   ├── MANUAL_REVIT_TEST.md       # live-Revit checklist (Phase 1+)
│   └── RUNBOOK.md                 # Phase 10
├── packages/
│   └── contracts/                 # ★ single source of truth
│       ├── schemas/
│       │   ├── chapter-layout.v2.3.json
│       │   ├── brief.v1.json
│       │   ├── command-envelope.v1.json      # wire = {payload, sig}; body schema in $defs
│       │   └── wss-messages.v1.json          # full discriminated union
│       ├── ops/
│       │   ├── registry.json      # allowlist; EMBEDS a JSON Schema per op's args
│       │   └── param_allowlist.json
│       ├── catalogs/
│       │   ├── asbuilt_types.json            # thickness → CHPT_AsBuilt_* (human-supplied)
│       │   ├── new_construction_types.json   # wall/door/window type vocabulary (human-supplied)
│       │   ├── products.json                 # SKU/model/manufacturer (human-supplied, Phase 8)
│       │   └── plumbing.json                 # fixture-unit + drain data per fixture kind
│       ├── fixtures/
│       │   └── conformance/       # signed-envelope conformance manifest verified by TS+PY+C# in CI
│       ├── ts/                    # generated zod + types (json-schema-to-zod, pinned)
│       └── python/                # generated pydantic v2 (datamodel-code-generator, pinned)
├── services/
│   ├── gateway/                   # Node/TS: WSS server, envelope signing, REST API, auth,
│   │                              #   reviews/approvals endpoints, drift gate
│   ├── scan-converter/            # Python: Lane A (ezdxf) now, Lane B (open3d) Phase 9
│   ├── brief-extractor/           # Python: transcript → BriefSchema (Anthropic API)
│   ├── layout-compiler/           # Python: brief → ChapterLayout (Anthropic API + validator)
│   ├── agents/
│   │   ├── architectural/         # layout diff (exact id-join spec, Part G) → ops
│   │   ├── interior/              # greedy wall-seeking + bounded free-standing placement
│   │   ├── mep/                   # rules P1–P4, E1–E4
│   │   └── merge_gate/            # branch merge + clash Phase A + Phase-B recovery loop
│   ├── aidm-bridge/               # view exports → control maps → AIDM job → render refs
│   └── spec-compiler/             # parameter export → CSI MasterFormat docx/pdf
├── plugin/
│   ├── ChapterHub.Core/           # ★ plain net8.0, ZERO Revit references:
│   │   │                          #   envelope verify (HMAC/TTL/seq), contract records,
│   │   │                          #   mm→ft conversion, queue/batch logic, id-map model
│   │   └── (xUnit-tested in CI on Linux)
│   ├── ChapterHub.Core.Tests/     # xUnit: pure logic + conformance vectors + fixture validation
│   └── ChapterHub.Revit.Addin/    # net8.0-windows + Nice3point Revit API NuGet (compile-only),
│       │                          #   EnableWindowsTargeting=true for Linux CI builds
│       ├── src/Transport/         # WSS client (background thread)
│       ├── src/Execution/         # ExternalEvent handler: ONE envelope per pass (Part G)
│       ├── src/Ops/               # one handler class per allowlisted op
│       └── src/IdMap/             # logical id (W-001) → ElementId + last-committed seq,
│                                  #   persisted via Extensible Storage
├── tools/
│   ├── revit-sim/                 # Python: headless mock executor, same WSS protocol,
│   │                              #   in-memory model + SVG plan renderer (canonical output:
│   │                              #   sorted elements, fixed 1-decimal-mm rounding, stable ids)
│   └── fixtures-gen/              # synthetic point-cloud generator (Phase 9 ground truth)
├── fixtures/
│   ├── scans/2br_uws.dxf          # Lane A golden input (create in Phase 2)
│   ├── transcripts/               # synthetic only (SI-11); incl. injection-attack fixtures
│   ├── layouts/minimal.json       # Phase 0 acceptance fixture
│   ├── layouts/2br_golden.json
│   └── goldens/*.svg              # rendered plan snapshots (structural compare)
└── infra/                         # Azure notes (deploy is Phase 10, ask first)
```

Tooling: `pnpm` workspaces (TS), `uv` (Python), `dotnet 8` SDK, `ruff` + `pytest`, `eslint` + `vitest`, `xUnit`. Postgres via docker-compose only. **Redis is removed until a phase has concrete work for it** (v1.0 declared it but assigned it nothing); re-adding it is a deliberate decision, not plumbing-by-default.

---

## PART D — CONTRACTS (Phase 0 deliverables)

**The JSON Schema files in `packages/contracts/schemas/` and `packages/contracts/ops/` are the canonical, normative artifacts** — created in Phase 0 and thereafter changed only under Rule 2. This section specifies their required content. (v1.0 embedded full schema JSON here; v1.1 moves authority to the files to eliminate doc/file drift — the v1.0 text is the repository's initial commit on `main`, and `docs/PLAN_REVIEW.md` records every delta per finding.)

### D1. `chapter-layout.v2.3.json` — the layout document

v2.3 = v2.2 plus the review amendments. Requirements:

- `meta.required` = `project_id, level, units, origin, schema_version, brief_version, phase` — **`origin` is now required** (const `"revit_internal_origin"`); `schema_version` const `"2.3"`.
- `meta.levels` carries `floor_z`, `ceiling_z` (finished ceiling), and **`slab_to_slab`** — the plumbing datum from which `h_plenum = slab_to_slab − (ceiling_z − floor_z)` is derived for Part G P-4. Conditional rule: a layout whose `meta.scan.capture == "pointcloud"` **requires** `floor_z` and `ceiling_z` (Lane B measures them); Lane A (`capture == "floorplan_dxf"`) cannot, so there they come from the review-card-confirmed ceiling height. Validator asserts `floor_z < ceiling_z ≤ floor_z + slab_to_slab`.
- `meta.electrical.panel` (pt2, optional): the panel location consumed by Part G E-4. Fallback: nearest `risers[type="electrical"]`; if neither exists, E-4 emits REVIEW with a human-suppliable field on the review card.
- `meta.scan`: adds `capture: "floorplan_dxf" | "pointcloud"`; `cloud_ref` is a **pattern-constrained opaque id** (`^[a-z0-9][a-z0-9_-]{0,63}$`), never a URL or path.
- **Rooms carry an ordered `boundary` polygon** (array of pt2, ≥ 3 vertices, required) in addition to `boundary_wall_ids`; the deterministic validator checks the polygon is simple, closed (first≠last, implicit closure), consistent with the wall centerlines (every edge within half the host wall's thickness of some boundary wall), and that `boundary_wall_ids`/`adjacent_room_ids` items match `^W-[0-9]{3}$` / `^R-[0-9]{3}$`. Room area and all inside-room predicates derive from `boundary`.
- **Furniture items carry semantics, not just geometry**: required `kind` enum (`wc, lav, shower, tub, kitchen_sink, dishwasher, washer, dryer, range, oven, refrigerator, sofa, bed, table, chair, desk, wardrobe, generic`), optional `fixture_units` (number, defaults per kind from `catalogs/plumbing.json`) and `hookups[]` (enum: `sanitary, supply_h, supply_c, vent, gas, electrical_120, electrical_240`). Part G P-1/P-3/P-4 and E-2 read these fields — never family-name string matching.
- New **`casework[]`** array: wall-anchored counter/cabinet runs (`id ^K-[0-9]{3}$, host_wall_id, offset, length, depth, height, is_counter, revit_family, revit_type`). E-2's "counter walls" are walls hosting `is_counter` casework.
- `footprint` uses a new `$defs.size2` = `[width_mm, depth_mm]`, both `exclusiveMinimum: 0` (v1.0 reused the pt2 point type). Semantics: `rotation_deg` rotates the width axis CCW about `center`; clash Phase A uses the rotated oriented rectangle, the sim's AABB is that rectangle's bounding box.
- **No `default` keywords anywhere in the schemas** — defaults live in code (`packages/contracts` documents them per field). This makes the round-trip acceptance test well-defined in all three languages.
- **`additionalProperties: false` on every nested object** (meta, wall/door/window/room/furniture/casework/column/riser items) — a misspelled flag must fail validation, not silently default. (The envelope's per-op `args` stay open at the envelope level; the registry's per-op `args_schema` closes them.)
- `revit_type` / `revit_family` remain strings in the schema but are **catalog-constrained at validation time**: generated (`source="generated"`) elements must use vocabulary from `catalogs/new_construction_types.json`; scan walls resolve via `catalogs/asbuilt_types.json`. Enforced by the layout validator AND by revit-sim (so CI mirrors the live-Revit failure mode).
- Scope: **single-level apartments only** in v2.3, stated here explicitly. The Phase 2 gateway rejects multi-level Polycam bundles with a clear message (never silently flattens). Multi-level (levels[], per-element level_id, stair entity) is a deliberate future schema version.
- Everything else (walls/doors/windows/risers/columns/constraints shapes, id patterns, maxItems, mm units) carries over from v2.2.

### D2. `brief.v1.json` — structured client brief

As v1.0, with the same two mechanical changes: no `default` keywords, `additionalProperties: false` on every nested object. Fields: meta (project_id, brief_version, source_sessions, confirmed_by_client), rooms_required, adjacency_rules, style_tags (≤ 12, each ≤ 40 chars), finish_tier, keep_items, special_constraints, open_questions, contradictions. **`confirmed_by_client` is enforced**: the layout-compiler refuses briefs where it is not true (Part E Phase 4).

### D3. `command-envelope.v1.json` + WSS protocol

**Wire format (v1.1 — the central signing change):**

```json
{ "payload": "<JSON string: the EnvelopeBody, serialized ONCE by the gateway>", "sig": "<hex HMAC-SHA256 over the exact UTF-8 bytes of payload>" }
```

- `EnvelopeBody` (schema in `$defs`): `envelope_id (uuid), project_id (uuid), workstation_id, seq (int ≥ 1), issued_at (date-time), ttl_s (10–3600), commit_label?, approval_ref?, ops[1..1000]` where each op is `{op, args}`.
- The gateway canonicalizes (RFC 8785) once when producing `payload`; **verifiers (plugin, sim) HMAC the received `payload` bytes verbatim and only then parse it** — cross-language canonical-JSON byte-identity is no longer a correctness dependency of verification. Verification order: sig → parse payload → body schema → TTL → seq (re-checked at Execute time against the persisted last-committed seq, per SI-3) → per-op `args_schema` from the registry → enqueue. Any failure → `ack rejected`, never partial execution.
- **`workstation_id` is inside the signed body** — an envelope for workstation A cannot be replayed to workstation B. The gateway enforces exactly one active executor (connected plugin) per project.
- **`approval_ref`** (optional; **required for commit-class envelopes** — Commit #0/#1/#2): `{review_id, content_hash}` binding the human-approved review-card content into the signature, so a compromised gateway cannot silently commit geometry nobody approved (Part F threat model).
- **seq semantics:** the plugin checks `seq` at Execute time (Revit API thread) against the **last-committed seq persisted in Extensible Storage inside the same TransactionGroup as the ops** — so a rollback releases the seq and the gateway may re-issue under the same or a fresh seq. HMAC + TTL are checked on the network thread at enqueue; TTL is **re-checked at dequeue** (an envelope deferred past its TTL by a modal Revit session is rejected with a distinct reason). On document open the plugin reads last-committed seq + an id-map hash from Extensible Storage and reports both in `hello`, so the gateway resumes from the model's truth (a model restored from backup rolls seq and id-map back **together**).
- **Key lifecycle:** per-project key = `HKDF(master, project_id)` (reconciling the single master env var with per-project keys). Delivery: at workstation enrollment, over the authenticated WSS channel, bound to the per-workstation auth token; stored via DPAPI on the workstation. Rotation procedure in the Phase 10 runbook (dual-accept grace window). *Flagged decision (docs/PLAN_REVIEW.md): upgrading to Ed25519 (gateway signs, plugins hold only a public key) removes workstation key secrecy entirely; the wire format above is signature-scheme agnostic so this swap stays cheap.*

**`wss-messages.v1.json` is a full discriminated union** (top-level `oneOf` on required `type` const), not prose. Messages (fields fully typed in the schema file):
`hello {workstation_id, plugin_version, open_project_id?, last_committed_seq, id_map_hash}` · `auth_ok` · `auth_error {reason}` · `envelope {payload, sig}` · `ack {envelope_id, status: accepted|rejected, reason?}` · `busy {envelope_id, reason}` (Revit modal/unavailable — gateway defines timeout behavior for accepted-but-unexecuted envelopes) · `progress {envelope_id, ops_done, ops_total}` · `commit_result {envelope_id, status: committed|rolled_back, id_map_delta: [{logical_id, element_id}], errors: [{op_index?, code, message}]}` · `export_ready {kind: view|parameters|deviation|model_state, blob_ref}` · `clash_delta {envelope_id, pairs: [{a_id, b_id, kind}]}` · `state_divergence {last_valid_seq, id_map_hash, detail?}` (sent when the plugin detects undo/redo or missing HUB-created elements via DocumentChanged) · `error {code, message}`.

All `blob_ref` values are pattern-constrained opaque ids resolved only against the configured blob store; the plugin downloads into a fixed sandbox directory with a size cap, and the gateway validates plugin-supplied refs in `export_ready` the same way.

### D4. Op registry (allowlist — the ONLY things the plugin can do)

**`ops/registry.json` is machine-checkable**: one entry per op with an embedded JSON Schema 2020-12 **`args_schema`** (sharing `$defs` pt2/pt3/size2/id patterns), plus `revit_mapping` and `sim_behavior` strings. Gateway (before signing), sim, and plugin (before enqueue) all validate every `ops[i].args` against `args_schema` — the plugin enforces strict shape (required members, unknown-member rejection, types, tuple arity) from Phase 0 via its hand-maintained arg records, and picks up the full value constraints (ranges, enums, patterns) with the op handlers in Phase 1. The table below is the human-readable index; the file is normative.

| op | args (all mm / degrees) | Revit API mapping | revit-sim behavior |
|---|---|---|---|
| `create_level` | name, elevation | `Level.Create` | add level record |
| `create_wall` | id, start, end, revit_type, height, phase, flags{} | `Wall.Create(doc, Line, typeId, levelId, h, 0, false, structural)` + phase param | add wall; duplicate id or unknown catalog type → reject |
| `create_door` | id, host_wall_id, offset, revit_type, width, height, swing, flip_facing | `NewFamilyInstance(pt, symbol, hostWall, level, NonStructural)` | add opening; offset within host length |
| `create_window` | id, host_wall_id, offset, sill_height, revit_type, width, height | same, hosted | same |
| `place_family` | id, revit_family, revit_type, center, rotation_deg, footprint, level | `NewFamilyInstance` + `ElementTransformUtils.RotateElement` | add instance with oriented footprint + AABB |
| `place_device` | id, kind: receptacle\|switch\|gfci, host_wall_id, offset, height_afl | face-hosted `NewFamilyInstance` | add device point |
| `create_pipe` | id, system: sanitary\|supply_h\|supply_c\|vent, pipe_type, level, path[[x,y,z]...], diameter | `Pipe.Create` per segment; **fittings: standard 90°/45° elbows only in v1 — tee/wye into stacks emits REVIEW for manual completion** (Revit fitting insertion is the least reliable MEP API; requires template with routing preferences, runbook item) | add polyline with radius |
| `create_conduit` | id, level, path[[x,y,z]...], diameter | `Conduit.Create` per segment | add polyline |
| `set_parameter` | target_id, param, value — **param must be in `ops/param_allowlist.json`** (finish/material/comment params only) | `Parameter.Set` | update record |
| `set_phase_demolished` | target_id | set `PHASE_DEMOLISHED` | mark record demolished |
| `delete_element` | target_id — **valid only for `source="generated"` elements** (SI-8 protects existing) | `doc.Delete` | remove record; reject for scan-sourced ids |
| `update_wall` | id, start?, end?, height?, revit_type? — **generated walls only** | geometry/type edit via location curve + type change | update record; reject for scan-sourced ids |
| `link_pointcloud` | blob_ref — **pre-indexed .rcs/.rcp (or E57 on 2025+) only; indexing happens out-of-band before the envelope is issued** (watcher/CLI on the workstation or pre-supplied in the upload bundle — never inside an op/transaction) | `PointCloudType.Create` + instance, pinned | no-op, record ref |
| `export_views` | views[{name, kind: plan\|section\|3d_hidden, px}] | `ImageExportOptions` → PNG → upload blob → `export_ready` | render SVG → **rasterize to PNG at requested px** → blob (bridge consumes one format from both executors) |
| `export_parameters` | categories[] | `FilteredElementCollector` harvest → JSON blob | dump records |
| `verify_deviation` | wall_ids[], tolerance_mm | sample `PointCloudInstance.GetPoints` near faces, RMS per wall | synthetic pass/fail from fixture |
| `verify_model_state` | element_ids[] (empty = all id-mapped) | existence + geometry hash per id-mapped element → JSON blob → `export_ready {kind: model_state}` | hash records |
| `run_interference_check` | scope: last_commit | `ElementIntersectsElementFilter` over created set | oriented-footprint overlap check |

Adding an op requires: registry entry with args_schema + plugin handler + sim handler + tests + human sign-off. There is no other execution path.

---

## PART E — PHASE PLAN

Rough effort assumes agentic development, one engineer reviewing. Dependencies are strict; Phase 3 is parallel-eligible alongside 1–2.

| Phase | Deliverable | Depends on | Rough effort |
|---|---|---|---|
| 0 | Scaffold + contracts + codegen + CI | — | **~1 week** |
| 1 | Spine: gateway + plugin skeleton + revit-sim + approvals API | 0 | 1.5–2 weeks |
| 2 | Lane A scan → Revit (Commit #0) | 1 | 1 week |
| 3 | Brief extractor | 0 *(parallel-eligible)* | 4 days |
| 4 | Layout compiler + Architectural Agent (Commit #1) | 1, 3 | 1.5 weeks |
| 5 | Interior Agent (wall-seeking + free-standing) | 4 | 4–5 days |
| 6 | MEP Agent + merge gate + clash recovery (Commit #2) | 4, 5 | 2 weeks |
| 7 | AIDM bridge + finish selection | 4 | 4–5 days |
| 8 | Spec compiler | 6, 7 | 1 week |
| 9 | Lane B point-cloud extractor | 2 | 2–3 weeks |
| 10 | Hardening + deploy (Azure) | all | 1 week |

### Phase 0 — Scaffold, contracts, codegen, CI
**Build:** repo tree (Part C); the four schemas per Part D (v2.3 layout, no defaults, nested strictness); `ops/registry.json` **with embedded args_schema per op**; `ops/param_allowlist.json` (seeded with the finish/material/comment params); `catalogs/` seeded with placeholder files + README marking the human-supplied entries (**ask Eran for**: as-built wall type names/thicknesses, new-construction type vocabulary from Chapter's template); codegen: `json-schema-to-zod` (pinned) → TS, `datamodel-code-generator` (pinned, recent enough for prefixItems tuples) → pydantic v2, **hand-written C# records in `ChapterHub.Core`** validated against shared fixtures (Rule 4); **a signing conformance manifest** in `packages/contracts/fixtures/conformance/` (payload strings + key + expected outcome per case, incl. tamper/replay/TTL/sig-format/schema-invalid/unknown-op/invalid-args negatives and the TTL boundary) verified by TS, Python, AND C# tests in CI; `docker-compose` with postgres; `Makefile` targets `codegen`, `test`, `verify`, `dev-up`; GitHub Actions running lint + tests for TS and Python, `dotnet build` on the solution and `dotnet test` on `ChapterHub.Core.Tests` (Linux runners; the Addin project sets `EnableWindowsTargeting`).
**Acceptance:**
- [ ] `make verify` green locally and in CI
- [ ] `fixtures/layouts/minimal.json` validates in all three languages (generated TS/Python types; C# records with strict unknown-member rejection)
- [ ] Round-trip test: parse → serialize → canonical-byte-identical in TS and Python (JCS libs, pinned); semantic deep-equality + strict-member round-trip in C#
- [ ] Signing conformance vectors verify identically in TS, Python, and C# (positive + tampered + wrong-key)
- [ ] Registry test: a known op with schema-invalid args fails validation in TS and Python validators
**Demo:** CI badge green; `fixtures/layouts/minimal.json` validating in TS, Python, C#.

### Phase 1 — The spine (gateway ⇄ plugin/sim over signed WSS)
**Build:**
- `services/gateway`: WSS server; per-workstation auth token + enrollment (key delivery per D3); envelope builder + HMAC signer (HKDF per project; master key from env, later Key Vault); Postgres tables `projects`, `envelopes`, `event_log`, `id_map`, `reviews`; REST endpoints `POST /projects/:id/envelopes` (service-auth only), `GET /projects/:id/state`, **and the approvals surface: `GET /projects/:id/reviews`, `POST /reviews/:id/approve|reject` (actor identity recorded)** — with `AUTO_APPROVE=1` honored only in CI e2e. **All REST endpoints authenticate and authorize per project (SI-10)**: service-to-service token for internal calls; HUB identity for humans. Drift gate wiring: before building any envelope after Commit #0, issue `verify_model_state` and route mismatches to REVIEW.
- `tools/revit-sim`: Python WSS client implementing the full protocol; in-memory model; enforces sig/TTL/seq exactly like the plugin (payload-bytes HMAC, per-envelope atomicity, Execute-time seq); SVG plan renderer with **canonical output** (sorted element order, fixed 1-decimal-mm rounding, stable ids) + PNG rasterization, so goldens are deterministic by construction; catalog-membership rejection for unknown revit_types.
- `plugin/ChapterHub.Core` + `ChapterHub.Revit.Addin`: per Part C split. Pin exact Nice3point Revit API package versions when they are added here, and plan the TFM bump for Autodesk's in-service Revit 2025/2026 migration to .NET 10 (.NET 8 EOL Nov 2026). Executor per the Part G reference: **one envelope per Execute pass, its own TransactionGroup, per-envelope `commit_result`, re-Raise while queue non-empty**; document binding (project_id stamped in Extensible Storage at Commit #0, verified before every TG; `ActiveUIDocument == null` guarded; mismatch → `ack rejected {wrong_document}`); seq + id-map persisted in Extensible Storage inside the TG; mm→ft conversion; op handler registry (`IOpHandler` per op). All pure logic (verify, conversion, queue, batching, seq/TTL) in Core, xUnit-covered — no Revit runtime in tests, enforced by a CI assertion that Core references no Revit assembly.
**Acceptance:**
- [ ] E2E in CI: gateway signs an envelope with 4 `create_wall` ops → revit-sim commits → `commit_result` recorded → sim SVG matches golden
- [ ] Tampered signature / replayed seq / expired TTL / unknown op / **schema-invalid args on a known op** / **wrong workstation_id** → `ack rejected`, nothing partially applied (tests)
- [ ] Two envelopes where the second fails → first committed, second rolled back alone; per-envelope `commit_result` (test)
- [ ] Sim restart mid-stream → resumes from persisted last-committed seq via `hello` resync (test)
- [ ] Cross-language conformance: the C# Core verifier accepts/rejects the gateway-emitted fixture vectors identically to TS and Python (CI)
- [ ] Unauthenticated / cross-project REST call → 401/403, no envelope signed (SI-10 test)
- [ ] Sim-vs-plugin placement cross-check: revit-sim and the plugin's pure-logic placement code (ChapterHub.Core) compute identical door/window/device placement points from the same envelope (revit-6)
- [ ] `dotnet build` (Core + Addin) + Core unit tests green in CI
- [ ] **Gate checklist (human):** load plugin in Revit, run the 4-wall envelope live, see 4 walls; record in docs/MANUAL_REVIT_TEST.md
**Demo:** `make demo-phase1` runs the E2E and opens the SVG.

### Phase 2 — Lane A scan converter (Polycam DXF → Commit #0)
**Build:** `services/scan-converter/lane_a.py`: parse Polycam floor-plan DXF with `ezdxf`; **units: detect `$INSUNITS`; when 0/absent, fall back to a bounding-box magnitude heuristic (span 3–30 m → mm vs inch vs m) and require review-card confirmation of the detected unit**; extract wall polylines → centerline `(start, end)` pairs + thickness; **ARC/bulge segments tessellated into chords (max sagitta 10 mm) chained as flagged `curved_approximation` walls — never dropped or silently chorded without a flag**; map openings if present in DXF layers; snap headings within ±1.5° to dominant axes, preserve and flag genuine skews; **wall height defaults to a project ceiling height entered/confirmed by the human on the review card** (Lane A DXFs are 2D; stamped low-confidence; Lane B supersedes from measured floor_z/ceiling_z); emit `ChapterLayout` `meta.phase="existing"`, `capture="floorplan_dxf"`, per-element `confidence`; wall-type resolution from `catalogs/asbuilt_types.json` (**ask Eran for the real type names/thicknesses — placeholder names will not resolve on the live template**). Gateway flow: upload bundle → convert → review card (extracted lines, flags, unit + ceiling-height confirmations) → on approval (approval_ref into the envelope), build envelope → Commit #0. **Multi-level bundles rejected with a clear message.** Create `fixtures/scans/2br_uws.dxf` (synthetic realistic 2BR prewar: ~75 m², one skewed wall, one curved bay return, demising walls on two sides, kitchen/bath back-to-back).
**Acceptance:**
- [ ] Golden: fixture DXF → layout JSON → envelope → sim → SVG matches golden
- [ ] Thickness classification test (±10 mm buckets)
- [ ] Skew preservation test; orthogonal walls snap exactly
- [ ] Unit-detection tests: inches vs mm identical; **$INSUNITS=0 fixture → heuristic + review-card confirmation required**
- [ ] Arc tessellation test: curved bay → chained chord walls, flagged
- [ ] Elements below confidence 0.85 appear in review payload; review payload includes the height assumption
- [ ] **Gate checklist (human):** one real Commit #0 from a real Polycam DXF on the live workstation
**Demo:** drop a DXF into `make demo-phase2` → plan SVG + review payload printed.

### Phase 3 — Brief extractor (transcripts → BriefSchema)
**Build:** as v1.0 (normalize → classify → tool-enforced extraction → reconcile → persist), plus: **the PII scrub is specified and tested** — seeded names/emails/addresses/phone numbers are redacted before the API call and before any fixture recording; **recorded fixtures are generated from synthetic transcripts only** (SI-11). Transcripts enter prompts exclusively as delimited data blocks (SI-7). All LLM calls mocked in CI; one live smoke behind `RUN_LIVE_LLM=1`.
**Acceptance:** as v1.0 (golden brief, injection fixture with zero-ops assertion, contradiction fixture, repair-retry) plus:
- [ ] PII fixture: seeded PII never reaches the API-call boundary or recorded fixtures (test)
**Demo:** `make demo-phase3` prints brief JSON + contradiction diff from two fixture sessions.

### Phase 4 — Layout compiler + Architectural Agent (Commit #1)
**Build:** `services/layout-compiler`: **refuses briefs without `confirmed_by_client=true`**; brief + existing layout → LLM call producing `ChapterLayout` `phase="new"` constrained by: demising/load-bearing/exterior immutable, new walls inside envelope, risers passed through, **`revit_type`/`revit_family` from `catalogs/new_construction_types.json` (closed vocabulary injected into the prompt; validator enforces membership; sim rejects unknowns)**; deterministic validator (schema + referential integrity + geometry: room boundary polygons simple/consistent, doors within host, min widths, circulation per Part G's operational definition) with bounded repair loop (≤ 2) → REVIEW on failure. `agents/architectural`: **exact diff spec (Part G): join new layout to frozen Commit #0 by id; every `source="scan"` element must match its frozen counterpart within 1 mm or the layout is rejected pre-repair; id renumbering rejected** → ops (`create_wall/door/window`, `set_phase_demolished` for existing walls absent from the new plan) → **layout review card (existing vs new SVG side-by-side + demolition list) — human approval is mandatory before Commit #1** (approval_ref in the envelope) → Commit #1 → snapshot FROZEN.
**Acceptance:** as v1.0 (golden, property test, demising immutability, demolition-by-phasing) plus:
- [ ] Injection-laundering fixture: hostile brief free-text (notes/special_constraints/keep_items) → layout invariants hold (demising untouched, deltas within bounds vs golden)
- [ ] Diff-identity test: mocked LLM perturbs one kept wall's coordinates and one id → rejected, never demolish+create
- [ ] Unknown revit_type from compiler → rejected by validator AND by sim (negative test)
**Demo:** transcript → brief → new plan SVG side-by-side with existing plan SVG + the review card.

### Phase 5 — Interior Agent
**Build:** on the frozen snapshot: wall-seeking greedy per Part G (**including the item's 90° rotation on each candidate wall — bound 2×81 per wall**); **`wall_seeking=false` items get a bounded local search around the LLM-proposed center (spiral offsets ≤ 500 mm, 4 rotations, same shapely clearance predicates) — else REVIEW** (v1.0 gave free-standing items no algorithm at all); unplaceable → REVIEW. Emits `place_family` ops (with footprint).
**Acceptance:**
- [ ] Zero footprint overlaps across **all** placed items — both classes (property test, 200 seeded rooms)
- [ ] Door-swing arcs never intersect furniture (test)
- [ ] Iteration bounds respected (≤ 162 candidates/wall; ≤ spiral cap) (counter assertion)
- [ ] Unplaceable oversized item → flagged, not force-placed
**Demo:** furnished plan SVG for the golden 2BR.

### Phase 6 — MEP Agent + merge gate (Commit #2)
**Build:** `agents/mep` implementing Part G P-1…P-4, E-1…E-4 exactly (fixture data from furniture `kind`/`fixture_units`/`hookups` + `catalogs/plumbing.json`; panel from `meta.electrical.panel` or riser fallback). `agents/merge_gate`: Interior + MEP branch deltas; clash Phase A via shapely 2.5D prisms in an STRtree sweep; priority table; lower priority re-plans locally. **Clash recovery is specified end-to-end: `clash_delta` from a rolled-back Commit #2 returns to the merge-gate, which re-plans lower-priority elements under a shared Phase-A+Phase-B iteration budget (total ≤ 3, then REVIEW); on `rolled_back`, branches are retained, the snapshot remains at Commit #1, and the rebuilt merged envelope is re-issued under a fresh seq.**
**Acceptance:** as v1.0 (receptacle property test with 1 mm epsilon on boundary comparisons, counter-circuit, plumbing L_max, wet-wall consolidation, injected clash ≤ 3 iterations) plus:
- [ ] E-3 latch-side switch test; E-4 route test (avoids wet-stack prism; fire-rated penetration penalty applied — 4000 mm equivalent)
- [ ] Phase-B recovery test: sim rejects twice, third merged envelope commits — or REVIEW fires
- [ ] **Pre-phase gate checklist (human):** live spike executing one `create_pipe`, `create_door`, `place_device` envelope in Revit to validate the D4 mappings before the agent is built against them
**Demo:** plan SVG with device symbols, pipe/conduit polylines, stack marker; clash report JSON.

### Phase 7 — AIDM bridge + finish selection
**Build:** after Commit #1/#2, `export_views` (plan/section/3D hidden-line, 2048 px; **sim rasterizes SVG→PNG so the bridge consumes one format from both executors**); preprocess → Canny + MLSD line maps (**depth channel dropped in v1.1 — nothing in the system produces depth; line maps alone are standard for interior ControlNet-style conditioning; if depth is later wanted, pin a specific monocular model and give its test a tolerance**); compose prompt from `constraints.style_tags` treated strictly as data (sanitized/allowlisted vocabulary) into Chapter's fixed template; dispatch to AIDM (mocked in CI); render refs → review payload. **On approval, the designer makes a structured finish selection — per-room/per-surface SKUs from `catalogs/products.json` filtered by `finish_tier` — the render is illustrative, the selection is the data** that feeds the `set_parameter` envelope (allowlisted params only) and later Division 09.
**Acceptance:**
- [ ] Control-map generation golden test (fixture PNG → deterministic edge outputs)
- [ ] AIDM contract test against mock; retry/backoff
- [ ] Approval → `set_parameter` envelope uses only allowlisted params (negative test)
- [ ] Hostile style_tags fixture → template treats tags as data (injection test)
**Demo:** `make demo-phase7` produces control maps + a stubbed render + a finish-selection payload side-by-side.

### Phase 8 — Spec compiler
**Build:** `export_parameters` → element/parameter JSON; join against `catalogs/products.json` (**ask Eran for the 30 real Chapter SKUs at phase start — critical path**); category → CSI MasterFormat mapping **including casework (06 41 00 / 12 35 30) and demolition (02 41 19, sourced from `set_phase_demolished` records)**; Division 09 sources: wall finishes from Phase 7 selections; **floor/ceiling finishes are explicitly de-scoped in v1 (no floor/ceiling model elements exist) and the spec marks them "BY SEPARATE SCHEDULE"** — adding create_floor/create_ceiling + per-room finishes is a flagged future schema decision; unmapped → "UNSPECIFIED" + flag. **Catalog governance:** products.json is human-owned, semver'd, and a catalog version is pinned per project at commit time so re-generated specs are reproducible. Render docx + PDF; register in HUB.
**Acceptance:** as v1.0 (golden docx structural compare, UNSPECIFIED flagging, Phase 7 finish verbatim in Division 09) plus:
- [ ] Demolished walls appear under 02 41 19 (test)
**Demo:** open the generated spec PDF for the golden 2BR.

### Phase 9 — Lane B point-cloud extractor
**Build:** as v1.0 (register/clean → RANSAC planes → floor/ceiling → occupancy rasters → line extraction → paired parallels), except **opening classification replaces the three fixed slices with a per-candidate-gap vertical occupancy profile (100 mm z-bins over full wall height), classifying by sill/header extraction from the profile — fixing high-sill windows (sill 1200–1800 mm, schema-legal) that the slice table provably misclassified as solid wall; cased openings are defined as bounded gaps between collinear co-thickness segments (gap ≤ 2500 mm)**. `tools/fixtures-gen` hardened: Gaussian noise **plus low-frequency registration warp (1–3 cm sinusoidal), baseboard/radiator strips, open door leaves in gaps, partial glass returns, mirror dropout** — accuracy reported per artifact class. `verify_deviation` gate: RMS > 20 mm → REVIEW.
**Acceptance:** as v1.0 (15 mm centerline / 10 mm thickness on 10 synthetic units; F1 ≥ 0.95 incl. high-sill window cases; mirror dropout flagged; scale-factor path) plus:
- [ ] **One real tape-measured Polycam capture of a known unit as a non-CI, human-verified acceptance artifact with its own (looser, recorded) tolerance** — synthetic self-consistency is not field accuracy
**Demo:** cloud slice PNG with extracted lines overlaid + plan SVG vs ground truth.

### Phase 10 — Hardening + deploy (ask before every cloud step)
**Build:** structured logging + OpenTelemetry; rate limits; Key Vault signing keys **with the plugin-side rotation procedure (dual-accept grace window) in the runbook**; dead-letter queue for failed envelopes (Postgres-backed); **retention policy extended to transcripts, briefs, and scan blobs (not just the event log), plus an Anthropic data-handling review as a deploy-gate checklist item**; `docker-compose.prod.yml`; Azure notes (provisioning requires explicit approval); **runbook additions: MCP bridge disabled/removed on production workstations (SI-9), ReCap/template prerequisites, plugin install, replay recovery**.
**Acceptance:**
- [ ] Full golden E2E (`make e2e`): transcript + DXF → every phase (AUTO_APPROVE=1 for gates) → spec PDF, one CI job, < 10 min warm (registry-cached images; cold/warm budget recorded)
- [ ] Chaos tests: gateway restart mid-envelope → idempotent via persisted seq; plugin/sim restart → hello resync
- [ ] Security test suite (Part F) green — including SI-9/SI-10/SI-11 tests

---

## PART F — SECURITY INVARIANTS (each gets an automated test; violating one fails CI)

**Threat model.** Envelope signing defends the workstation against everything that is *not* the gateway: channel tampering, replay (seq + TTL + workstation binding), cross-project and cross-workstation injection, and non-gateway cloud services. It does **not** defend against a compromised gateway — the gateway authors envelopes. That residual risk is bounded by: `approval_ref` binding human-approved content into commit-class envelopes (a compromised gateway cannot silently commit unapproved geometry), the op allowlist (worst case is bounded, parameterized model edits — never code), per-project HKDF keys (blast radius), SI-10 (nobody but authenticated services reaches the signer), and Phase 10 rate limits + event log. Workstation-side key secrecy is the weakest link of symmetric HMAC; the Ed25519 upgrade decision is flagged in docs/PLAN_REVIEW.md.

- **SI-1** No LLM output is ever executed, eval'd, or templated into code or API calls. LLM output paths terminate in schema-validated JSON documents only.
- **SI-2** The plugin and sim execute only ops present in `ops/registry.json` with args valid against that op's embedded `args_schema`; unknown op **or schema-invalid args** → whole envelope rejected.
- **SI-3** Every envelope is HMAC-verified over the received payload bytes, TTL-checked at enqueue **and re-checked at dequeue**, and strictly sequence-monotonic against the last-committed seq persisted in the model, before any execution.
- **SI-4** `set_parameter` is restricted to `ops/param_allowlist.json`.
- **SI-5** Every envelope executes atomically in **its own** `TransactionGroup`: assimilate-or-rollback; no partial commits; per-envelope `commit_result`.
- **SI-6** All solver loops are bounded (greedy ≤ 162 candidates/wall; free-standing spiral ≤ cap; clash re-plan Phase A+B total ≤ 3; LLM repair ≤ 2) and time-limited.
- **SI-7** Transcripts and all client uploads are untrusted data end-to-end; they never appear in a system/instruction role — and the injection test suite covers every LLM-consuming service (extractor, compiler, AIDM prompt), not just the first.
- **SI-8** Existing-conditions elements marked demising/load-bearing/exterior are immutable to all agents; removal only via `set_phase_demolished` after human-reviewed Commit #0. `delete_element`/`update_wall` are valid only for `source="generated"` elements.
- **SI-9** On production workstations, the plugin's verified envelope queue is the **only** execution path into Revit; no MCP or scripting bridge runs alongside it (decommission is a Phase 10 runbook item; the Phase 1–4 de-risk adapter runs only under Part B's constraints).
- **SI-10** Every REST/WSS surface authenticates and authorizes per project; `POST /projects/:id/envelopes` is reachable only with service credentials. Unauthenticated or cross-project calls → 401/403, no envelope signed.
- **SI-11** Client PII is scrubbed before any LLM call and before any fixture recording; repo fixtures are synthetic only; retention policies cover transcripts, briefs, and scan blobs.

---

## PART G — ALGORITHM REFERENCE (implement exactly)

**Projection primitive (used everywhere).** Point `C` onto wall `(P₁,P₂)`:
`t* = clamp(((C−P₁)·(P₂−P₁)) / ‖P₂−P₁‖², 0, 1)`; foot `F = P₁ + t*(P₂−P₁)`; room-facing unit normal `n̂` = the normal of (P₂−P₁) pointing into the room's `boundary` polygon (test: `F + ε·n̂` inside polygon).
Fixture/furniture back-to-wall placement: `P = F + n̂·(t_wall/2 + t_finish + d_item/2)`.

**Room geometry.** All room predicates run on the ordered `boundary` polygon (D1). Room area = shoelace over `boundary`. **Circulation check (operational definition):** the room's free-space polygon (boundary minus placed footprints inflated by clearances) eroded by `circulation_min/2` must keep every door threshold in a single connected component (shapely: `free.buffer(-circulation_min/2)`, then connectivity of threshold points).

**Element identity across commits (Phase 4 diff).** Join the new layout to the frozen Commit #0 snapshot **by id**. Every element with `source="scan"` must match its frozen counterpart to within **1 mm** on all coordinates and identical flags — otherwise the layout is **rejected before the repair loop** (never demolish+create). Renumbering of existing ids is rejected. `set_phase_demolished` is emitted only for frozen ids absent from the new layout. A mocked-LLM acceptance test perturbs one kept wall and one id and asserts rejection.

**Greedy wall-seeking (Interior).** Items sorted by footprint area desc; walls nearest-first; per wall, both the item's natural orientation and its 90° rotation; tangential slides `s ∈ {0, ±50, …, ±2000}` mm (81 slides × 2 orientations = **162 candidates/wall**); accept first candidate inside room ∧ footprint-clear (inflated by `clearance_front`) ∧ clear of door-swing arcs ∧ circulation holds; else next wall; exhausted → REVIEW. **Free-standing (`wall_seeking=false`) items:** bounded spiral search around the proposed center (offsets ≤ 500 mm in 50 mm rings, 4 rotations) under the same predicates; else REVIEW.

**MEP rules.** (Fixture semantics come from furniture `kind`, `fixture_units`, `hookups` and `catalogs/plumbing.json` — never family-name matching.)
- **P-1 wet-wall selection:** candidates = walls with ≥ 1 adjacent wet room; `S(w) = Σ FU` over adjacent-room fixtures (WC 4, shower 2, kitchen sink 2, lav 1 — defaults in catalogs/plumbing.json); pick argmax; riser bias term `−λ·dist(w, riser)` with **`λ = 0.0005 FU/mm`** (≡ 0.5 FU/m; dist in mm per Rule 8). Unit-sanity property test asserts the bias term is the same order of magnitude as FU scores.
- **P-2 fixture snap:** projection primitive onto the selected wet wall.
- **P-3 stack position:** `t_s = Σ(FUᵢ·tᵢ*) / Σ FUᵢ` along the wet wall.
- **P-4 branch feasibility:** slope `s` is size-dependent — `s = 0.0208` (¼″/ft) for < 3″ pipe, `s = 0.0104` (⅛″/ft) for ≥ 3″ (IPC Table 704.1); `h_plenum` derives from `meta.levels.slab_to_slab` (D1); `L_max = (h_plenum − Ø_pipe − h_fitting)/s` with Ø from the fixture's drain size (catalogs/plumbing.json) and h_fitting from the same catalog; **`L` is the routed (Manhattan-along-walls) length from the P-2 projection foot to the stack**, not straight-line; violation → second stack, re-run P-1 on residual fixtures.
- **E-1 receptacles:** per continuous run `L` between openings, inset `a = 1830`, spacing `S = constraints.outlet_spacing` (default 3660): `N = max(1, ⌈(L−2a)/S⌉ + 1)`. **If `N = 1`, place the single device at `L/2` (explicit branch — no division).** Otherwise `xᵢ = a + i·(L−2a)/(N−1)`; **devices closer than 300 mm are deduped to one**; runs ≥ 610 mm get one; height 380 mm AFF. Test comparisons use ≤ with a 1 mm epsilon (values land exactly on limits by construction).
- **E-2 counters/GFCI:** counter walls = walls hosting `is_counter` casework. Spacing rule mirrors E-1 with **`a = 610`, `S = 1220`** at 1150 mm AFF (NEC 210.52(C): no point > 600 mm from a receptacle). **Every counter and bathroom receptacle is `kind=gfci`** (NEC 210.8 protection is per-area, not per-device); the ≤ 914 mm-from-basin rule is kept as the bathroom *placement* requirement.
- **E-3 switches:** latch side, 150 mm from jamb, 1220 mm AFF.
- **E-4 home-runs:** Dijkstra on wall-centerline graph + **panel node from `meta.electrical.panel` (fallback: nearest `risers[type=electrical]`; neither → REVIEW with human-suppliable review-card field)**; edge cost = `length_mm + 4000·(fire-rated penetrations)` (**4 m equivalent per penetration — v1.0's unitless +4 was numerical noise against mm lengths**) `+ ∞·(wet-stack exclusion prism: stack ± 300 mm)`; conduit elevation 2600 mm, vertical drops at devices.

**Clash priority:** structure 0 (never moves) → sanitary DWV 1 → supply 2 → HVAC 3 → electrical 4 → furniture 5. Lower priority re-plans; **Phase A + Phase B share one iteration budget: total ≤ 3, else REVIEW**; on a rolled-back Commit #2 the branches are retained, the snapshot stays at Commit #1, and the rebuilt envelope re-issues under a fresh seq.

**Opening classification (Lane B).** Per candidate gap, build a **vertical occupancy profile** (100 mm z-bins over the full wall height) from the point cloud; extract sill and header elevations from the profile. Classify: occupied full height → solid; gap floor-to-header → door (width = gap); gap sill-to-header with occupied below sill → window (**works for any schema-legal sill, incl. 1200–1800 mm — the v1.0 fixed-slice table provably misclassified those as solid**); full-height gap bounded by collinear co-thickness segments with gap ≤ 2500 mm → cased opening; otherwise → flagged low-confidence.
Orthogonality: snap ≤ ±1.5° to dominant axes; larger skews preserved + flagged.
**Deviation gate:** sample cloud points within 50 mm of each created wall face; RMS > 20 mm → REVIEW; Commit #0 requires human approval of the review card.

**Plugin executor core (reference shape — TG boundary = envelope boundary):**

```csharp
public class EnvelopeHandler : IExternalEventHandler {
    private readonly ConcurrentQueue<VerifiedEnvelope> _q = new();   // sig+TTL checked on network thread
    public void Enqueue(RawEnvelope e) { if (Core.VerifySigAndTtl(e)) { _q.Enqueue(Core.Parse(e)); _evt.Raise(); } else AckRejected(e); }
    public void Execute(UIApplication app) {                          // Revit UI thread only
        var uidoc = app.ActiveUIDocument;
        if (uidoc == null) return;                                    // re-raised on next enqueue/idle
        var doc = uidoc.Document;
        if (!_q.TryDequeue(out var env)) return;                      // ONE envelope per pass
        if (!Core.TtlStillValid(env) || !DocBinding.Matches(doc, env.ProjectId)
            || !SeqStore.IsNext(doc, env.Seq)) { AckRejected(env); RaiseIfPending(); return; }
        using var tg = new TransactionGroup(doc, $"HUB {env.EnvelopeId}");
        tg.Start();
        try {
            foreach (var batch in env.Ops.Chunk(200)) RunBatch(doc, batch);   // one Transaction per batch
            SeqStore.CommitSeq(doc, env.Seq);                          // Extensible Storage, inside the TG
            IdMap.Persist(doc, env.Delta);                             // rolls back WITH the ops
            tg.Assimilate();
            SendCommitResult(env, committed: true);
        } catch (Exception ex) { tg.RollBack(); SendCommitResult(env, committed: false, ex); }
        RaiseIfPending();                                              // drain queue one envelope at a time
    }
    public string GetName() => "Chapter HUB Executor";
}
```

The Addin also subscribes to `DocumentChanged`; detected undo/redo touching HUB-created elements sends `state_divergence {last_valid_seq, id_map_hash}` so the gateway marks the project dirty and forces the drift gate.

---

## PART H — TESTING & CI

- `make verify` = lint + typecheck + unit + contract tests, all languages (dotnet: build Core+Addin, test Core).
- `make e2e` = full golden pipeline against revit-sim, LLM mocked, `AUTO_APPROVE=1`, < 10 min warm (cached images; cold/warm budget recorded in CI).
- Golden SVG snapshots compared structurally (parsed elements, per-coordinate tolerance) — deterministic by construction (canonical sim renderer).
- Cross-language conformance vectors (signed envelope bytes incl. negatives) verified by TS, Python, and C# in every CI run.
- Property tests (`hypothesis`) for: receptacle spacing, furniture non-overlap (both placement classes), layout validator, P-1 unit sanity.
- Injection suite spans brief-extractor, layout-compiler, and AIDM prompt composition (SI-7).
- Live LLM smoke tests only behind `RUN_LIVE_LLM=1`, never in CI.
- Plugin: `dotnet build` + xUnit on Core in CI; `docs/MANUAL_REVIT_TEST.md` covers live-Revit verification — required at the Phase 1, 2, and pre-6 gates, then per release.

## PART I — ENVIRONMENT

`.env.example` (never commit real values):

```
DATABASE_URL=postgres://chapter:chapter@localhost:5432/revit_agent
ANTHROPIC_API_KEY=            # brief-extractor, layout-compiler
LLM_MODEL_EXTRACTOR=claude-sonnet-5   # pin; upgrade deliberately
LLM_MODEL_COMPILER=claude-opus-5      # layout generation is the hardest spatial-reasoning call
ENVELOPE_MASTER_KEY=          # dev only; per-project keys = HKDF(master, project_id); Key Vault in prod
BLOB_CONNECTION_STRING=       # Azure Blob (exports, renders, clouds)
AIDM_ENDPOINT=                # existing AIDM service; mocked when empty
RUN_LIVE_LLM=0
AUTO_APPROVE=0                # 1 only in CI e2e — approval gates are real in every other context
```

## PART J — DO NOT

- Do not add dependencies on Revit runtime to anything outside `plugin/ChapterHub.Revit.Addin`.
- Do not bypass the envelope path "just for testing" — the sim exists for that; the MCP adapter only under Part B's constraints.
- Do not let any service construct op lists from unvalidated LLM text (SI-1/SI-2).
- Do not auto-resolve REVIEW flags; they surface via the approvals API, humans clear them (`AUTO_APPROVE` is CI-only).
- Do not implement Lane B before Lane A is demoable (Phase order is deliberate).
- Do not orthogonalize walls silently; skews are preserved and flagged.
- Do not invent catalog vocabulary (wall types, SKUs) — those entries are human-supplied; placeholders must be marked and never shipped.
- Do not store secrets or client PII in code, fixtures, or test snapshots.
- Do not attempt Azure provisioning, Polycam account changes, or Revit installation — ask.

---

## AMENDMENTS (v1.1)

Index of every change from v1.0, each traceable to a finding id in `docs/PLAN_REVIEW.md`.

**Contracts**
1. `ops/registry.json` format specified: embedded JSON Schema `args_schema` per op; gateway+sim+plugin all validate; schema-invalid-args acceptance tests added (contracts-1).
2. `wss-messages.v1.json` specified as a full discriminated union with typed `id_map_delta`, `clash_delta`, errors, auth handshake; new `busy`, `state_divergence` messages (contracts-2, revit-3, revit-8).
3. Envelope wire format = `{payload, sig}`; verifiers HMAC received payload bytes verbatim — cross-language RFC 8785 byte-identity removed as a verification dependency (delivery-4, contracts-3).
4. `default` keywords removed from all schemas; defaults live in code; round-trip acceptance redefined per language (contracts-3, contracts-8).
5. Key lifecycle specified: HKDF per-project derivation, enrollment delivery, DPAPI storage, rotation runbook; `workstation_id` in signed body; one active executor per project; Ed25519 upgrade flagged as an open decision (security-1, security-6).
6. Rooms carry an ordered `boundary` polygon; circulation operationally defined (algorithms-1).
7. `footprint` → `size2` with positivity + rotation semantics; footprint added to `place_family` (contracts-4).
8. `origin` required; Lane-B layouts require floor/ceiling; `slab_to_slab` plumbing datum; `meta.electrical.panel` (contracts-5, algorithms-5, critic-4).
9. `additionalProperties:false` on all nested objects; id patterns on room reference arrays; shared referential-integrity validator (contracts-6).
10. Furniture `kind`/`fixture_units`/`hookups`; `casework[]` entity; `catalogs/plumbing.json` (product-5).
11. `param_allowlist.json` + `catalogs/` placed in the tree; generated `revit_type`/`revit_family` catalog-constrained, enforced by validator AND sim (contracts-7, delivery-6, critic-6, security-4).
12. `verify_model_state` op + gateway drift gate + resync path; `DocumentChanged` divergence detection (product-1, revit-8).
13. `delete_element` / `update_wall` ops (generated-only) + revision-loop semantics (product-2).
14. `blob_ref`/`cloud_ref` pattern-constrained opaque ids; sandboxed downloads (security-8).
15. Single-level scope stated; multi-level bundles rejected explicitly (product-8).
16. Layout schema bumped to **v2.3**; Part D now defers to `packages/contracts/schemas/` as the canonical artifacts to eliminate doc/file drift.

**Part G**
17. Executor: one envelope per Execute pass, own TransactionGroup, per-envelope commit_result, re-Raise drain (revit-1).
18. seq at Execute time vs last-committed seq persisted in Extensible Storage inside the TG; hello resync; TTL re-check at dequeue (revit-2, security-6).
19. Document binding: project_id stamped via Extensible Storage, verified pre-TG; null-doc guard (revit-3, product-4).
20. Phase 4 diff identity spec: id join, 1 mm epsilon, rejection on renumbering; perturbation acceptance test (critic-1).
21. Unit fixes: E-4 penalty 4000 mm-equivalent; P-1 λ = 0.0005 FU/mm + unit-sanity test (algorithms-4).
22. E-1 N=1 branch explicit, 300 mm dedupe, epsilon comparisons; E-2 end-inset 610 mm; all counter/bath receptacles GFCI (algorithms-8).
23. P-4: size-dependent slope, routed length, plenum/drain/fitting data sources named (algorithms-5).
24. Door/window `offset` = mm from wall `start` to opening centerline; side/swing conventions pinned; sim-vs-plugin placement cross-check (revit-6).
25. Lane B: per-gap vertical occupancy profile replaces fixed slices (high-sill windows fixed); cased-opening definition; fixtures-gen hardened; real-capture acceptance (algorithms-2, algorithms-3).
26. Lane A: arc tessellation with flags; $INSUNITS=0 fallback + review confirmation; wall height from review-card ceiling height (algorithms-7, critic-7).
27. Interior: 90° rotation searched (162 candidates/wall); free-standing bounded spiral; overlap property covers both classes (algorithms-6).
28. Clash recovery: Phase A+B shared ≤ 3 budget; rolled-back Commit #2 state transition defined (critic-5).

**Phases & process**
29. Approvals REST surface in Phase 1 + `AUTO_APPROVE=1` CI path; brief `confirmed_by_client` enforced; HUB-vs-portal UI decision flagged to Eran (delivery-1, product-3).
30. Mandatory human approval before Commit #1; `approval_ref` binds approved content into commit-class envelopes (security-4, security-2).
31. Plugin solution split Core/Addin; `EnableWindowsTargeting`; tests on Core only + no-Revit-reference CI assertion; Nice3point versions pinned, .NET 10 migration noted (revit-7, delivery-5).
32. Cross-language signing conformance vectors verified by TS+Python+C# in CI (critic-3).
33. Live-Revit smokes are required gate items at Phases 1, 2, pre-6 (delivery-2).
34. `create_pipe` v1 scoped to segments + 90/45 elbows; tees → REVIEW; template routing-preferences prerequisite (revit-4).
35. Point-cloud indexing out-of-band; `link_pointcloud` links pre-indexed files only (revit-5).
36. Phase 7: depth channel dropped; sim rasterizes SVG→PNG; structured finish selection feeds set_parameter + Division 09; catalog governance (critic-2, product-7).
37. Phase 8: casework + demolition CSI divisions; floor/ceiling finishes explicitly de-scoped with the future decision flagged (product-6).
38. Part F: threat-model paragraph; SI-9 (single execution path / MCP decommission), SI-10 (REST authn/z), SI-11 (PII + synthetic fixtures); injection suite spans all LLM consumers (security-2, -3, -5, -7, critic-8).
39. Phase 0 re-budgeted ~1 week; C# = hand-written records + fixture tests (Rule 4 amended); Redis removed until needed; Phase 3 parallel-eligible; SVG goldens canonical-by-construction; CI image caching (delivery-4, -7, -8).

One review finding was **refuted** and its substantive asks deliberately not applied (a claimed Phase 6/7 dependency-table contradiction — a misreading of Rule 1's strict ordering; Phase 7 still depends on 4). Its cosmetic table clarification (listing 5 in Phase 6's row and 7 in Phase 8's row, which strict ordering made implicit) WAS applied. See docs/PLAN_REVIEW.md.

**Open decisions for Eran** (do not block Phase 0; block the phases noted): Ed25519 vs HMAC (Phase 1); review-card UI in existing HUB vs new minimal portal (Phase 2); catalog contents — as-built types, new-construction vocabulary, 30 SKUs (Phases 2/4/8); multi-level support timing (future schema version); floor/ceiling finish modeling (Phase 8+).
