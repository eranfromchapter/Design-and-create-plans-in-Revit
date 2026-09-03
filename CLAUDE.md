# Chapter Revit AI Agent — Claude Code operating guide

## What this repo is
Hybrid Revit-AI system: cloud orchestrator (Node/TS gateway + Python services) plans;
a C#/.NET 8 Revit plugin executes signed, allowlisted operations. See PLAN.md (v1.1) for the
full build plan and docs/PLAN_REVIEW.md for the pre-build design review it incorporates.
Work one phase at a time; stop at every phase gate.

## Hard rules
- packages/contracts is the single source of truth. TS/Python types are generated from the
  schemas (pinned generators); C# records are hand-maintained in ChapterHub.Core but
  CI-verified against the shared fixtures and conformance vectors. Regenerate after schema edits.
- Security Invariants SI-1..SI-11 in PLAN.md Part F are absolute. Tests enforce them.
- All coordinates in contracts are millimeters. Plugin converts to Revit feet (/304.8).
  Every Part G scoring constant is stated in mm.
- Every solver loop is bounded and time-limited.
- Envelope verification checks the Ed25519 signature over the received payload bytes
  verbatim (wire = {payload, sig}); never verify a reserialized object. Private keys live
  only in the gateway; executors hold pinned public keys.
- Never run against live Revit from CI; use tools/revit-sim. Plugin compiles + unit-tests only
  (ChapterHub.Core carries all pure logic; the Addin project has zero tests).
- Catalog vocabulary (wall types, SKUs) is human-supplied — never invent it; placeholders are
  marked and never shipped.
- Ask before: cloud provisioning, secrets, contract schema changes, new ops, Revit-machine steps.

## Commands
- make dev-up        # postgres (services + revit-sim join the compose stack in Phase 1)
- make codegen       # regenerate TS/Python types + conformance vectors from schemas
- make verify        # lint + typecheck + all unit/contract tests (TS, Python, C#)
- make e2e           # full-stack spine suite: real gateway + real sim child processes
                     #   (needs postgres; Phase 10 grows this into the golden pipeline)
- make demo-phase1   # golden 4-wall pipeline; plan SVG at fixtures/goldens/phase1_4walls.svg

## Conventions
- TS: Node 22, pnpm, strict, eslint, vitest, zod at boundaries.
- Python: 3.12, uv, ruff, pytest, pydantic v2, shapely for 2D geometry, hypothesis for
  property tests. FastAPI for services.
- C#: .NET 8. ChapterHub.Core = plain net8.0, zero Revit references, xUnit-tested.
  ChapterHub.Revit.Addin = net8.0-windows + Nice3point Revit API NuGet (compile-only,
  EnableWindowsTargeting for Linux CI). CI asserts Core references no Revit assembly.
- LLM calls only in brief-extractor and layout-compiler, behind interfaces, mocked in CI.
  PII is scrubbed before any LLM call; repo fixtures are synthetic only (SI-11).
- One phase per branch/PR. Conventional commits. Fixtures + tests ship with features.

## Current status
Update this section at every phase gate: phase number, what passed, open REVIEW items.

- Phase 0: complete (PR #1). `make verify` green (TS + Python + C#); minimal.json validates
  in all three languages; signing conformance vectors verified cross-language.
- Phase 1: code complete (PR #2). Envelope signatures switched to Ed25519 (decided at
  the Phase 0 gate; conformance re-pinned, 19 vectors × 3 languages). Gateway (WSS + signer +
  approvals + drift gate), revit-sim, plugin Core+Addin (46 tests, Addin compile-only vs
  pinned Nice3point 2025.4.60), full-stack e2e green (golden 4-wall pipeline, rollback
  isolation, SIGKILL resync, SI-10, drift gate).
  OPEN GATE ITEM (human): live-Revit checklist, docs/MANUAL_REVIT_TEST.md Phase 1 section.
- Phase 2: code complete on this branch (Lane A). services/scan-converter (pure lane_a lib +
  FastAPI /convert + CLI, 40 tests; DXF profile v1 pinned in PROFILE.md as a documented
  assumption); gateway scan flow (scan-bundles → scan_commit0 review → approve with
  {unit, ceiling_height_mm} confirmations persisted in reviews.decision_payload → issue-commit0
  → commit0_done flips on commit_result; 35 gateway tests); fixture 2br_uws.dxf (17 walls incl.
  curved bay 7 chords + skew; spec module = provenance, entity-wise drift test); goldens
  2br_golden.json (semantic) + phase2_2br.svg (byte, eyeballed); phase2 e2e (3 child
  processes) green; make demo-phase2.
  OPEN GATE ITEM (human): docs/MANUAL_REVIT_TEST.md Phase 2 section — needs a real Polycam
  DXF + real as-built catalog names (profile calibration is the first checklist item).
  Gate question for Eran: add `skewed: boolean` to the wall schema? (Skews currently ride in
  review-payload flags + confidence only — no schema change without approval.)
- Phase 3: code complete on this branch. services/brief-extractor (normalize + PII scrub
  SI-11 → tool-enforced extraction vs brief.v1.json with 1 repair retry → deterministic
  latest-wins reconciliation + contradictions[] → injection guard SI-7; LLM behind
  ExtractorLLM — AnthropicLLM pinned via LLM_MODEL_EXTRACTOR, FixtureLLM replays the
  synthetic recordings in fixtures/llm; 40 tests + live smoke behind RUN_LIVE_LLM=1).
  Gateway briefs flow (POST /projects/:id/transcripts → versioned briefs table 0003 +
  client_brief review; approve → confirmed_by_client on row + content.meta — the flag the
  Phase 4 layout-compiler enforces; 40 gateway tests). Fixture transcripts + golden brief
  (2 contradictions: bedroom 3→4, tier premium→standard); phase3 e2e (extractor + gateway
  children) green; make demo-phase3.
  No human gate item this phase; live-LLM smoke awaits ANTHROPIC_API_KEY.
  Open items for Eran: catalog contents (as-built wall types incl. door/window placeholders
  now in asbuilt_types.json, new-construction vocabulary, 30 SKUs); ANTHROPIC_API_KEY for
  the Phase 3 live smoke.
- Phase 4: code complete on this branch. services/layout-compiler (deterministic validator:
  schema → referential/catalog/floating-wall/SI-7-output guards → geometry incl. 100mm-step
  edge sampling for collinear walls, per-program min widths, opening clear spans, envelope
  AABB vs frozen, Part G circulation with per-room threshold attribution; CompilerLLM seam
  — AnthropicLLM pinned via LLM_MODEL_COMPILER, FixtureLLM keyed by <brief sessions=...>;
  repair loop ≤2; architectural agent: Part G diff-identity 1mm epsilon, immutable
  demising/load-bearing/exterior walls, renumber detection, riser pass-through, demolition
  BY PHASING only; sim-replay preflight + review-card SVGs through the sim's canonical
  renderer — card new_svg is byte-identical to post-commit reality; 68 tests incl.
  hypothesis totality/epsilon properties). Gateway Commit #1 flow (migration 0004
  layout_snapshots FROZEN by construction — commit0 row = approved scan layout with
  confirmed ceiling, commit1 row = approved phase=new layout verbatim; compile-layout →
  layout_commit1 review {layout, ops, demolition_list, svgs}; failures → layout_failure
  review, never auto-approved; issue-commit1 sends content.ops verbatim under approval_ref;
  side-by-side review card; 48 gateway tests). Golden 4BR fixture (table-generated,
  drift-pinned: 15 kept walls verbatim, 4 demolished, 10 new walls + 8 doors + 11 rooms,
  22 ops) + fixtures/goldens/phase4_2br.svg (byte, eyeballed — demolished elements dashed);
  phase4 e2e (5 child processes, full phase-2→3→4 chain) green; make demo-phase4.
  GATE QUESTIONS FOR ERAN: (1) demising/load-bearing/exterior flags are never set by Lane A,
  so wall immutability is enforced but vacuous on real scans until the scan review card
  grows flag confirmation — Phase 5 item? (2) live-LLM risk: the spec requires the model to
  echo 17 scan walls to 1mm; fixture mode is exact, live failure rate unmeasured until
  ANTHROPIC_API_KEY lands. Standing asks unchanged (catalogs, API key, MANUAL_REVIT_TEST
  checklists for Phases 1–2).
- Phase 5: code complete on this branch (PR #6). Interior agent = furnish pass in
  services/layout-compiler (parallel InteriorLLM seam, LLM_MODEL_INTERIOR, forced
  emit_furniture = the contract furniture subtree only — walls/doors/rooms are data blocks;
  proposal repair ≤2 for schema/catalog/referential/dup-id errors only; catalog OVERWRITES
  footprint+clearance; 60s request-boundary timeout → 422) + deterministic Part G placer
  (interior.py: 162 candidates/wall slide-outer/orientation-inner, spiral cap 324, counter-
  asserted; predicates: covers → symmetric positive-area footprint-clear (touching legal) →
  swing arcs (swing.py pins: hinge offset∓w/2, leaf sweeps LEFT of start→end when
  flip_facing falsy, single swept-side room, pocket exempt, t_finish=0) → model-wide
  strict-< AABB (sim formula — run_interference_check can never fire on furniture) →
  incremental circulation via shared geometry.py; unplaceable → REVIEW, never forced).
  Furnished layout re-passes the FULL validator (furniture checks added: closed
  family/type/kind vocabulary, footprint pinned to catalog, inside-room, pairwise
  positive-area overlap, arc intersection; furniture ids in the dup-id sweep). Gateway
  furnish-layout → interior_plan review {layout, ops, svgs, unplaced, diagnostics, counts}
  — the BRANCH DELTA for Phase 6 (no envelope, no migration; PHASE 6 HANDOFF: merge gate
  reads the LATEST interior_plan review, requires approved else 409, content.ops verbatim
  as the interior half of Commit #2 under {review_id, content_hash}, content.layout.furniture
  seeds MEP, content.unplaced excluded); interior_failure never auto-approved;
  state.interior_plan_ready. Q7 SHIPPED: scan card wall-flag confirmations
  (decision_payload.wall_flags, ≤64, unknown ids 422) applied by commit0LayoutFromReview to
  BOTH the frozen snapshot and issue-commit0 ops (divergence fixed). Golden furnished 2BR:
  20 proposals → 18 placed / 2 REVIEW (F-013 bath2 lav, F-020 laundry washer — real
  geometric verdicts, the acceptance demos), generator gen_golden_furniture.py is the sole
  source of truth (validator oracle + eroded-area floors); phase5_2br_furnished.svg byte
  golden (eyeballed). 200-seeded-room property suite (zero overlaps both classes, arcs
  clear, validator oracle; odd seeds rigidly rotated by 11.25/22.5/30/45°). phase5 e2e
  (5 children, chain through furnish, card bytes == goldens, seq stays 2) green;
  make demo-phase5. Catalog gains 15 _PLACEHOLDER furniture families/types (human input);
  contracts README clearance defaults amended (per-type, absent=0, all-side inflation).
  ADVERSARIAL REVIEW (22 agents): 17 confirmed findings, all fixed on this branch —
  flip_facing now rides in create_door ops (committed ops = arc geometry), spiral anchor
  is the proposed center VERBATIM (out-of-room → REVIEW, never clamped), spiral rotations
  are proposal-relative, item ordering is GLOBAL (-area, id) across rooms (unplaced order
  pinned to attempt order: F-020 before F-013), pocket-door exemption unions both
  catalogs, plumbing closure via catalogs/plumbing.json (fixture_units overwritten,
  hookups = plumbing ∪ additive electrical/gas), the furnish deadline interrupts the
  solver itself (callback; interior.py stays clock-free by AST test), duplicate room
  groups are a repairable proposal error, session ids clamped to a safe charset at every
  boundary (gateway zod, extractor pattern, prompt builders), interior_plan_ready
  requires content.brief_version == latest CONFIRMED brief (staleness),
  COVER_TOLERANCE_MM=0.1 absorbs rotated-wall center rounding; sim interference check
  replayed for real in the golden test. Phase 6 design-review spill-over fixed here too:
  the inside-room predicate (placer + validator) tests the room's INNER-FACE polygon
  (geometry.room_inner_polygon = D1 boundary minus each wall's t/2 slab) — items may
  touch a wall face, never sink into a wall; golden re-pinned (F-008/F-009/F-011 moved,
  F-019 +51mm; still 18 placed / F-020, F-013 REVIEW).
  GATE ITEMS FOR ERAN: (1) clearance semantics — the field is named clearance_FRONT but
  the validator/Part G inflate all sides; front-only would be a validator/Part G change
  (bed clearance set to 0 for now: all-around 760 makes <2650mm bedrooms bed-less).
  (2) Golden reality: bath2 legally holds wc only; the frozen 1200×1200 laundry can't hold
  any 600mm appliance (D-011 swing) — both ship as REVIEW demos; alternatives touch Phase 4
  semantics. (3) Pinned v1 interpretations for sign-off: t_finish=0, spiral cap 324,
  swing/flip conventions, slide-outer nesting, positive-area overlap (touching legal),
  model-wide AABB as a deliberate 5th predicate. (4) Dry-appliance hookups
  (range 240V, fridge 120V, washer-stack +240V) are authored per-item, not yet catalog
  entries; the washer/dryer stack is ONE kind=washer item (Phase 6 never sees 'dryer').
  (5) Fixture chain stays flag-free by design — confirming wall flags on a real scan
  obliges the Phase 4 compiler to echo them (live behavior; immutability then bites).
  (6) brief.v1.json source_sessions has no charset pattern — runtime boundaries clamp to
  ^[A-Za-z0-9_-]{1,120}$ everywhere, but pinning it in the SCHEMA is a contract change
  needing approval. (7) PLAN Part H says "hypothesis" for the placer property suite; what
  shipped is a 200-case seeded-PRNG corpus + hypothesis on validator totality — reconcile
  or bless. (8) Catalog has no leafless/pocket door flag; the swing exemption is
  name-based ("pocket") — a real flag needs catalog vocabulary from Eran.
  Standing asks unchanged (catalogs, ANTHROPIC_API_KEY, MANUAL_REVIT_TEST Phases 1–2).
- Phase 6: code complete on this branch (PR #7, stacked on PR #6). Design in
  docs/PHASE6_DESIGN.md (37 PINs, refutation ledger) — normative. NO LLM, no schema change;
  registry: place_device.args.face (left|right, required) + kind receptacle_240 (Eran Q1).
  layout-compiler mep/ = deterministic Part G MEP agent: inputs (levels/panel stamped from
  meta → riser → card confirmations {panel, slab_to_slab_mm} → blocking items; wet rooms,
  fixture semantics from kind/FU/hookups + plumbing.json, placer host walls, derived counter
  walls), plumbing P-1 argmax ΣFU − λ·dist (λ=0.0005 FU/mm, SI-8 walls excluded) → P-2 → P-3
  FU-weighted t_s snapped out of door spans → P-4 L_max=(h_plenum−Ø−h_fitting)/slope with
  L = along (PIN-08, Eran Q3), prune → residual re-run (MAX_STACKS 4), branch TREE with honest
  z-profile; electrical E-1 kernel N=max(1,⌈(L−2a)/S⌉+1) + fixpoint dedupe <300, E-2 counter
  circuit + basin ≤914, E-3 latch-side switches with the corner/hinge fallback ladder,
  corridor/laundry/appliance (receptacle_240) extensions, GFCI area rule; E-4 canonical wall
  graph + state Dijkstra from the panel (cost = length + 4000·rated penetrations, stack ±300
  squares forbidden) → raceway tree at 2600. fittings.py is the C# PipePath twin (shared
  manifest). POST /plan-mep → MepPlan. merge/ = ONE clash law (catalogs/clash_prisms.json;
  Phase A oriented prisms ⊆ sim AABB law, exemption table proven shared with revit-sim and
  ChapterHub.Core): STRtree sweep → lower priority re-plans (furniture via
  legalize_furniture(preplaced, obstacles), device ±150·k, conduit reroute, relocate_stack;
  same priority → blocked; progress guarantee → drop; ids never renumber) under the SHARED
  ≤3-round budget; stateless replay of prior actions; POST /merge → MergeResult (interior ops
  verbatim + MEP ops + one trailing run_interference_check, validator oracle, sim preflight).
  Goldens (gen_golden_mep.py sole source of truth, eyeballed): 2 stacks (P-001 W-004 @5133.3
  Ø76 for F-006/F-007/F-012; P-002 W-026 @169 Ø51 snapped), 10 pipes, 45 devices (11 switches,
  4 gfci, 1 240V), 81 conduits, 155-op Commit #2, Phase A 0 clashes, real-sim commit;
  recovery E-001 1912.5→1762.5→1612.5 commits at plan 3 (iterations_used 2); exhaustion after
  4 rejects; gate note with both sides of PIN-08 (→3 stacks) and PIN-13 (no-op on this chain).
  Sim: MEP rendering (goldens 1–5 byte-stable), revit_sim.clash (created×all, strict <),
  TestHooks.inject_clash only behind --control-port. Gateway: migration 0005, plan-mep /
  merge-commit2 / issue-commit2 ladders, merge chain state derived from reviews+envelopes,
  MergeResult verified before any card, every rebuilt plan = NEW commit2_merge approval
  (Eran Q2), fresh seq per re-issue (PIN-30), clash signal authoritative from commit_result
  "A~B" errors (clash_delta supplementary, per-session frame serialization), commit2 snapshot,
  /state.commit2, mep_plan + commit2_merge cards, /envelopes approval_ref_required. Plugin:
  Core PipePath/ClashPairs/ClashExemptions/MepTypes (82 tests); Addin place_family,
  create_pipe/conduit (PIN-35 groups), place_device face-hosted, door flips,
  run_interference_check, clash_delta; catalogs enrolled beside the config. Tests: compiler
  461, gateway 73 (14 Phase 6), sim + C# green, e2e 10 suites incl. phase6 recovery +
  exhaustion; make demo-phase6.
  ADVERSARIAL REVIEW (46 agents: 10 dimension finders → 65 findings → 2-lens refutation of
  the top 18 → 17 confirmed; every confirmed finding plus the material unverified ones is
  fixed on this branch): stable conduit ids (drop Q-n ↔ device E-n, trunks from a fixed base,
  dropped ids reserved, dropped trunk GEOMETRY forbidden; devices that lose their only path
  are dropped + reported, never left conduit-less), fixture moves record a `replan_plumbing`
  action the verifier honours, device shifts clear the stack ±300 square and escalate to
  k 5..8 before dropping, Phase A acts on live pairs only, structure/structure pairs are
  existing conditions, P-4 governing fixture = highest pipe top, P-1 only on walls a fixture
  faces (unclamped feet), honest `snapped` flag, plumbing not blocked by electrical-only
  items, riser_adjacent from the stack, supply_manual incl. cold-only, E-3 latch corner from
  the ROOM edge at E3_CORNER_FALLBACK_MM, E-2 on every counter-owning room, side probes clear
  face-aligned boundaries (t/2 + tol), conduits/devices in ABSOLUTE z, Lane B partial
  meta.levels honoured, gateway /envelopes approval_ref must name the approved ops (SI-2),
  verifier completeness + review_id echoes, project-scoped commit_result/ack (SI-10),
  transient merge errors retryable, zod → 400, unreachable compiler → outcome, plugin
  interference wire message "A~B" (Detail), whole-document created×all sweep, sim codes
  aligned, malformed catalogs never take the add-in offline, sim boxes use as-built
  thickness and survive deleted hosts, inject test exercises the real law.
  DEVIATIONS FROM THE DESIGN (for sign-off): (a) conduit ids: drops are stable (Q-n ↔ E-n),
  trunks renumber from a fixed base on every raceway re-run and never reuse a dropped id;
  pipes are derived state whenever P-1..P-4 re-run (relocate_stack, or the recorded
  `replan_plumbing` after a plumbing fixture moved/dropped) — ids may renumber; the gateway
  verifier applies exactly these exemptions plus completeness (every approved op survives,
  is in `dropped`, or is derived) instead of the design's literal "every un-actioned op
  deep-equals"; (b) MEP card svg keys are {furnished, mep} (the design said commit1/mep);
  (c) a moved/dropped plumbing FIXTURE re-resolves inputs (its recorded host wall
  forgotten) and re-runs P-1..P-4 + E-4; (d) unknown clash ids are a contract error except
  `revit:<ElementId>` structure; (e) a dropped trunk's geometry stays forbidden, so devices
  whose only home run used it are dropped and reported (the alternative — re-emitting the
  clashing segment under a new id — was the confirmed high finding); (f) "Phase A == sim
  law" shipped as five forced device plans + the exemption table, not a random-model
  property; (g) PIN-35 extras (segments 2..n, elbows, group) are not persisted in the HUB
  id-map — invisible to DocumentChangedWatcher after Commit #2 (gate item).
  GATE ITEMS FOR ERAN: (1) clearance semantics — the field is named clearance_FRONT but
  the validator/Part G inflate all sides; front-only would be a validator/Part G change
  (bed clearance set to 0 for now: all-around 760 makes <2650mm bedrooms bed-less).
  (2) Golden reality: bath2 legally holds wc only; the frozen 1200×1200 laundry can't hold
  any 600mm appliance (D-011 swing) — both ship as REVIEW demos; alternatives touch Phase 4
  semantics. (3) Pinned v1 interpretations for sign-off: t_finish=0, spiral cap 324,
  swing/flip conventions, slide-outer nesting, positive-area overlap (touching legal),
  model-wide AABB as a deliberate 5th predicate. (4) Dry-appliance hookups
  (range 240V, fridge 120V, washer-stack +240V) are authored per-item, not yet catalog
  entries; the washer/dryer stack is ONE kind=washer item (Phase 6 never sees 'dryer').
  (5) Fixture chain stays flag-free by design — confirming wall flags on a real scan
  obliges the Phase 4 compiler to echo them (live behavior; immutability then bites).
  (6) brief.v1.json source_sessions has no charset pattern — runtime boundaries clamp to
  ^[A-Za-z0-9_-]{1,120}$ everywhere, but pinning it in the SCHEMA is a contract change
  needing approval. (7) PLAN Part H says "hypothesis" for the placer property suite; what
  shipped is a 200-case seeded-PRNG corpus + hypothesis on validator totality — reconcile
  or bless. (8) Catalog has no leafless/pocket door flag; the swing exemption is
  name-based ("pocket") — a real flag needs catalog vocabulary from Eran.
  Standing asks unchanged (catalogs, ANTHROPIC_API_KEY, MANUAL_REVIT_TEST Phases 1–2).
- Phase 6: code complete on this branch (PR #7, stacked on PR #6). Design in
  docs/PHASE6_DESIGN.md (37 PINs, refutation ledger) — normative. NO LLM, no schema change;
  registry: place_device.args.face (left|right, required) + kind receptacle_240 (Eran Q1).
  layout-compiler mep/ = deterministic Part G MEP agent: inputs (levels/panel stamped from
  meta → riser → card confirmations {panel, slab_to_slab_mm} → blocking items; wet rooms,
  fixture semantics from kind/FU/hookups + plumbing.json, placer host walls, derived counter
  walls), plumbing P-1 argmax ΣFU − λ·dist (λ=0.0005 FU/mm, SI-8 walls excluded) → P-2 → P-3
  FU-weighted t_s snapped out of door spans → P-4 L_max=(h_plenum−Ø−h_fitting)/slope with
  L = along (PIN-08, Eran Q3), prune → residual re-run (MAX_STACKS 4), branch TREE with honest
  z-profile; electrical E-1 kernel N=max(1,⌈(L−2a)/S⌉+1) + fixpoint dedupe <300, E-2 counter
  circuit + basin ≤914, E-3 latch-side switches with the corner/hinge fallback ladder,
  corridor/laundry/appliance (receptacle_240) extensions, GFCI area rule; E-4 canonical wall
  graph + state Dijkstra from the panel (cost = length + 4000·rated penetrations, stack ±300
  squares forbidden) → raceway tree at 2600. fittings.py is the C# PipePath twin (shared
  manifest). POST /plan-mep → MepPlan. merge/ = ONE clash law (catalogs/clash_prisms.json;
  Phase A oriented prisms ⊆ sim AABB law, exemption table proven shared with revit-sim and
  ChapterHub.Core): STRtree sweep → lower priority re-plans (furniture via
  legalize_furniture(preplaced, obstacles), device ±150·k, conduit reroute, relocate_stack;
  same priority → blocked; progress guarantee → drop; ids never renumber) under the SHARED
  ≤3-round budget; stateless replay of prior actions; POST /merge → MergeResult (interior ops
  verbatim + MEP ops + one trailing run_interference_check, validator oracle, sim preflight).
  Goldens (gen_golden_mep.py sole source of truth, eyeballed): 2 stacks (P-001 W-004 @5133.3
  Ø76 for F-006/F-007/F-012; P-002 W-026 @169 Ø51 snapped), 10 pipes, 45 devices (11 switches,
  4 gfci, 1 240V), 81 conduits, 155-op Commit #2, Phase A 0 clashes, real-sim commit;
  recovery E-001 1912.5→1762.5→1612.5 commits at plan 3 (iterations_used 2); exhaustion after
  4 rejects; gate note with both sides of PIN-08 (→3 stacks) and PIN-13 (no-op on this chain).
  Sim: MEP rendering (goldens 1–5 byte-stable), revit_sim.clash (created×all, strict <),
  TestHooks.inject_clash only behind --control-port. Gateway: migration 0005, plan-mep /
  merge-commit2 / issue-commit2 ladders, merge chain state derived from reviews+envelopes,
  MergeResult verified before any card, every rebuilt plan = NEW commit2_merge approval
  (Eran Q2), fresh seq per re-issue (PIN-30), clash signal authoritative from commit_result
  "A~B" errors (clash_delta supplementary, per-session frame serialization), commit2 snapshot,
  /state.commit2, mep_plan + commit2_merge cards, /envelopes approval_ref_required. Plugin:
  Core PipePath/ClashPairs/ClashExemptions/MepTypes (82 tests); Addin place_family,
  create_pipe/conduit (PIN-35 groups), place_device face-hosted, door flips,
  run_interference_check, clash_delta; catalogs enrolled beside the config. Tests: compiler
  461, gateway 73 (14 Phase 6), sim + C# green, e2e 10 suites incl. phase6 recovery +
  exhaustion; make demo-phase6.
  DEVIATIONS FROM THE DESIGN (for sign-off): (a) conduit ids are re-derived on every
  raceway re-run (drops keep their device pairing, trunks renumber) — the gateway verifier
  treats conduits as derived state and pipes as derived after relocate_stack, instead of
  the design's literal "every un-actioned op deep-equals"; (b) MEP card svg keys are
  {furnished, mep} (the design said commit1/mep); (c) a moved/dropped plumbing FIXTURE
  re-resolves inputs and re-runs P-1..P-4 + E-4 (design named furniture re-legalize only);
  (d) unknown clash ids are a contract error except `revit:<ElementId>` structure.
  GATE DECISIONS (Eran, 2026-09-03): (1) ⚠ PINs 08, 12, 13, 16, 17, 20, 29, 30, 37 BLESSED as
  shipped (no golden re-run); (2) catalog vocabulary stays _PLACEHOLDER for now — Eran will
  connect the real vocabulary through knowledge later (mep_types.json, clash_prisms.json
  heights/device box, counter casework family); (3) deviations (a)–(g) signed off; (4) the
  human Pre-Phase-6 Revit spike + Phase 6 checklist (docs/MANUAL_REVIT_TEST.md) stays OPEN —
  it needs a person at a Revit workstation, like the Phase 1–2 checklists; (5) v1 scope =
  sanitary DWV only confirmed; registry prose amendment for sim_behavior (Q5) folded into the
  Phase 7 contracts commit. Standing asks unchanged (catalog vocabulary via knowledge,
  ANTHROPIC_API_KEY, MANUAL_REVIT_TEST Phases 1–2 and 6).
