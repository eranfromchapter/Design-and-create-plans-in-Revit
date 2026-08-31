# Chapter Renovation — Revit AI Design & MEP Orchestration Agent

Hybrid Revit-AI system: a cloud orchestrator (Node/TS gateway + Python services + Anthropic
LLM calls) plans apartment renovations; a C#/.NET 8 Revit plugin executes HMAC-signed
envelopes of allowlisted, parameterized operations over WSS. A headless simulator
(`tools/revit-sim`) stands in for Revit in CI.

- **[PLAN.md](PLAN.md)** — the build plan (v1.1), executed one phase at a time with gates.
- **[docs/PLAN_REVIEW.md](docs/PLAN_REVIEW.md)** — the pre-build adversarial design review
  (55 accepted findings) whose amendments produced v1.1.
- **[CLAUDE.md](CLAUDE.md)** — operating guide + current phase status.

## Quick start

```bash
make verify     # lint + typecheck + all unit/contract tests (TS, Python, C#)
make codegen    # regenerate TS/Python types + conformance vectors from schemas
make dev-up     # postgres via docker compose
```

Toolchain: Node 22 + pnpm, Python 3.12 + uv, .NET 8 SDK.

## Status

**Phase 0 complete** (scaffold + contracts + codegen + CI). `packages/contracts` is the
single source of truth; the four schemas, the op registry (with embedded per-op args
schemas), and the cross-language signing conformance vectors are live in TS, Python, and C#.
Phase 1 (gateway ⇄ plugin/sim spine) starts on approval — see PLAN.md Part E.
