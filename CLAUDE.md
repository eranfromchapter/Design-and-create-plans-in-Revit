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
