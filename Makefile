# Chapter Revit AI Agent — Phase 0/1 targets (PLAN.md Part H).
# verify = lint + typecheck + unit + contract tests, all three languages.
# Gateway DB-backed tests and the e2e suite need Postgres (make dev-up) + DATABASE_URL;
# without it the gateway DB suite skips and e2e is a separate target.

# Fall back to dotnet-install.sh's default location when the SDK is not on PATH.
DOTNET ?= $(shell command -v dotnet 2>/dev/null || echo $(HOME)/.dotnet/dotnet)
PY_DIR := packages/contracts/python
TS_DIR := packages/contracts/ts
SIM_DIR := tools/revit-sim
DATABASE_URL ?= postgres://chapter:chapter@127.0.0.1:5432/revit_agent

.PHONY: verify lint typecheck test codegen codegen-check dev-up dev-down test-ts test-py test-cs e2e demo-phase1

verify: lint typecheck test codegen-check
	@echo "verify: all green"

lint:
	pnpm -r --if-present lint
	cd $(PY_DIR) && uv run ruff check . && uv run ruff format --check .
	cd $(SIM_DIR) && uv run ruff check . && uv run ruff format --check .

typecheck:
	pnpm -r --if-present typecheck

test: test-ts test-py test-cs

# e2e is excluded here: it is the separate full-stack target below (and TRUNCATE-based
# gateway unit tests must never share a database with a live e2e run).
test-ts:
	pnpm run test

test-py:
	cd $(PY_DIR) && uv run pytest -q
	cd $(SIM_DIR) && uv run pytest -q

test-cs:
	$(DOTNET) build plugin/ChapterHub.sln --nologo -v q
	$(DOTNET) test plugin/ChapterHub.sln --no-build --nologo -v q

codegen:
	cd $(TS_DIR) && node scripts/codegen.mjs
	bash $(PY_DIR)/scripts/codegen.sh
	uv run packages/contracts/scripts/gen_conformance.py

# CI hygiene: regenerating must be a no-op — generated code and conformance vectors are
# committed and may not drift from the schemas. `git add -N` makes brand-new (untracked)
# generated files fail the gate too.
codegen-check: codegen
	git add -N $(TS_DIR)/src/generated $(PY_DIR)/src/chapter_contracts/generated packages/contracts/fixtures/conformance packages/contracts/fixtures/idmap
	git diff --exit-code -- $(TS_DIR)/src/generated $(PY_DIR)/src/chapter_contracts/generated packages/contracts/fixtures/conformance packages/contracts/fixtures/idmap

# Full-stack Phase 1 suite: real gateway + real sim as child processes (needs Postgres).
e2e:
	cd $(SIM_DIR) && uv sync --quiet
	cd tests/e2e && DATABASE_URL=$(DATABASE_URL) pnpm vitest run

# Phase 1 demo (Part E): runs the golden 4-wall pipeline and names the plan artifact.
demo-phase1:
	cd $(SIM_DIR) && uv sync --quiet
	cd tests/e2e && DATABASE_URL=$(DATABASE_URL) pnpm vitest run phase1
	@echo "demo-phase1: plan SVG at fixtures/goldens/phase1_4walls.svg"

dev-up:
	docker compose up -d

dev-down:
	docker compose down
