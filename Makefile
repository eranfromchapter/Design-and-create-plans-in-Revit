# Chapter Revit AI Agent — Phase 0 targets (PLAN.md Part H).
# verify = lint + typecheck + unit + contract tests, all three languages.

# Fall back to dotnet-install.sh's default location when the SDK is not on PATH.
DOTNET ?= $(shell command -v dotnet 2>/dev/null || echo $(HOME)/.dotnet/dotnet)
PY_DIR := packages/contracts/python
TS_DIR := packages/contracts/ts

.PHONY: verify lint typecheck test codegen codegen-check dev-up dev-down test-ts test-py test-cs

verify: lint typecheck test codegen-check
	@echo "verify: all green"

lint:
	pnpm -r --if-present lint
	cd $(PY_DIR) && uv run ruff check . && uv run ruff format --check .

typecheck:
	pnpm -r --if-present typecheck

test: test-ts test-py test-cs

test-ts:
	pnpm -r --if-present test

test-py:
	cd $(PY_DIR) && uv run pytest -q

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

dev-up:
	docker compose up -d

dev-down:
	docker compose down
