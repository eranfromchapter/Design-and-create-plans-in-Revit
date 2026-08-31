# Chapter Revit AI Agent — Claude Code operating guide

## What this repo is
Hybrid Revit-AI system: cloud orchestrator (Node/TS gateway + Python services) plans;
a C#/.NET 8 Revit plugin executes signed, allowlisted operations. See PLAN.md for the
full build plan. Work one phase at a time; stop at every phase gate.

## Hard rules
- packages/contracts is the single source of truth. Regenerate types after schema edits.
- Security Invariants SI-1..SI-8 in PLAN.md Part F are absolute. Tests enforce them.
- All coordinates in contracts are millimeters. Plugin converts to Revit feet (/304.8).
- Every solver loop is bounded and time-limited.
- Never run against live Revit; use tools/revit-sim. Plugin must compile + unit-test only.
- Ask before: cloud provisioning, secrets, schema changes, new ops, Revit-machine steps.

## Commands
- make dev-up        # postgres + redis + services + revit-sim
- make codegen       # regenerate TS/Python/C# types from schemas
- make verify        # lint + typecheck + all unit/contract tests
- make e2e           # golden pipeline end-to-end (LLM mocked)
- make demo-phaseN   # phase demo artifact

## Conventions
- TS: Node 22, pnpm, strict, eslint, vitest, zod at boundaries.
- Python: 3.12, uv, ruff, pytest, pydantic v2, shapely for 2D geometry, hypothesis for
  property tests. FastAPI for services.
- C#: .NET 8, Nice3point Revit API NuGet (compile-only), xUnit for pure logic.
- LLM calls only in brief-extractor and layout-compiler, behind interfaces, mocked in CI.
- One phase per branch/PR. Conventional commits. Fixtures + tests ship with features.

## Current status
Update this section at every phase gate: phase number, what passed, open REVIEW items.
