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
- Phase 1: code complete on this branch. Envelope signatures switched to Ed25519 (decided at
  the Phase 0 gate; conformance re-pinned, 19 vectors × 3 languages). Gateway (WSS + signer +
  approvals + drift gate, 21 tests), revit-sim (31 tests), plugin Core+Addin (46 tests,
  Addin compile-only vs pinned Nice3point 2025.4.60), full-stack e2e suite green (5 tests:
  golden 4-wall pipeline, rollback isolation, SIGKILL resync, SI-10, drift gate).
  OPEN GATE ITEM (human): live-Revit checklist, docs/MANUAL_REVIT_TEST.md Phase 1 section.
  Open items for Eran: catalog contents (as-built wall types, new-construction vocabulary,
  30 SKUs).
