# Chapter Revit AI Agent — Phase 0/1 targets (PLAN.md Part H).
# verify = lint + typecheck + unit + contract tests, all three languages.
# Gateway DB-backed tests and the e2e suite need Postgres (make dev-up) + DATABASE_URL;
# without it the gateway DB suite skips and e2e is a separate target.

# Fall back to dotnet-install.sh's default location when the SDK is not on PATH.
DOTNET ?= $(shell command -v dotnet 2>/dev/null || echo $(HOME)/.dotnet/dotnet)
PY_DIR := packages/contracts/python
TS_DIR := packages/contracts/ts
SIM_DIR := tools/revit-sim
SCAN_DIR := services/scan-converter
BRIEF_DIR := services/brief-extractor
LAYOUT_DIR := services/layout-compiler
DATABASE_URL ?= postgres://chapter:chapter@127.0.0.1:5432/revit_agent

.PHONY: verify lint typecheck test codegen codegen-check dev-up dev-down test-ts test-py test-cs e2e demo-phase1 demo-phase2 demo-phase3 demo-phase4 demo-phase5 demo-phase6

verify: lint typecheck test codegen-check
	@echo "verify: all green"

lint:
	pnpm -r --if-present lint
	cd $(PY_DIR) && uv run ruff check . && uv run ruff format --check .
	cd $(SIM_DIR) && uv run ruff check . && uv run ruff format --check .
	cd $(SCAN_DIR) && uv run ruff check . && uv run ruff format --check .
	cd $(BRIEF_DIR) && uv run ruff check . && uv run ruff format --check .
	cd $(LAYOUT_DIR) && uv run ruff check . && uv run ruff format --check .

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
	cd $(SCAN_DIR) && uv run pytest -q
	cd $(BRIEF_DIR) && uv run pytest -q
	cd $(LAYOUT_DIR) && uv run pytest -q

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

# Full-stack suite: real converter + extractor + gateway + sim as child processes
# (needs Postgres).
e2e:
	cd $(SIM_DIR) && uv sync --quiet
	cd $(SCAN_DIR) && uv sync --quiet
	cd $(BRIEF_DIR) && uv sync --quiet
	cd $(LAYOUT_DIR) && uv sync --quiet
	cd tests/e2e && DATABASE_URL=$(DATABASE_URL) pnpm vitest run

# Phase 1 demo (Part E): runs the golden 4-wall pipeline and names the plan artifact.
demo-phase1:
	cd $(SIM_DIR) && uv sync --quiet
	cd tests/e2e && DATABASE_URL=$(DATABASE_URL) pnpm vitest run phase1
	@echo "demo-phase1: plan SVG at fixtures/goldens/phase1_4walls.svg"

# Phase 2 demo (Part E): full Lane A pipeline on the 2BR fixture, then the review
# payload a human would see on the card.
demo-phase2:
	cd $(SIM_DIR) && uv sync --quiet
	cd $(SCAN_DIR) && uv sync --quiet
	cd tests/e2e && DATABASE_URL=$(DATABASE_URL) pnpm vitest run phase2
	cd $(SCAN_DIR) && uv run python -m scan_converter ../../fixtures/scans/2br_uws.dxf --review
	@echo "demo-phase2: plan SVG at fixtures/goldens/phase2_2br.svg"

# Phase 3 demo (Part E): full brief pipeline on the fixture transcripts, then the
# brief JSON + contradiction diff from the two sessions.
demo-phase3:
	cd $(BRIEF_DIR) && uv sync --quiet
	cd tests/e2e && DATABASE_URL=$(DATABASE_URL) pnpm vitest run phase3
	cd $(BRIEF_DIR) && uv run python -m brief_extractor \
	  ../../fixtures/transcripts/session1_3br.txt ../../fixtures/transcripts/session2_4br.txt

# Phase 4 demo (Part E): the full chain e2e, then the compiler CLI on the
# recorded fixture — writes the side-by-side card SVGs + ops for eyeballing.
demo-phase4:
	cd $(SIM_DIR) && uv sync --quiet
	cd $(SCAN_DIR) && uv sync --quiet
	cd $(BRIEF_DIR) && uv sync --quiet
	cd $(LAYOUT_DIR) && uv sync --quiet
	cd tests/e2e && DATABASE_URL=$(DATABASE_URL) pnpm vitest run phase4
	cd $(LAYOUT_DIR) && uv run python scripts/demo_phase4.py
	@echo "demo-phase4: golden plan SVG at fixtures/goldens/phase4_2br.svg"

# Phase 5 demo (Part E): the interior chain e2e, then the furnish CLI on the
# recorded fixture — furnished plan SVG + the ops + the REVIEW list.
demo-phase5:
	cd $(SIM_DIR) && uv sync --quiet
	cd $(SCAN_DIR) && uv sync --quiet
	cd $(BRIEF_DIR) && uv sync --quiet
	cd $(LAYOUT_DIR) && uv sync --quiet
	cd tests/e2e && DATABASE_URL=$(DATABASE_URL) pnpm vitest run phase5
	cd $(LAYOUT_DIR) && uv run python scripts/demo_phase5.py
	@echo "demo-phase5: furnished plan SVG at fixtures/goldens/phase5_2br_furnished.svg"

# Phase 6 demo (Part E): deterministic MEP plan + merge gate on the recorded chain —
# MEP card, merged Commit #2 card, clash report, the two-reject recovery replay and
# the gate note to out/phase6/, after the phase6 e2e (recovery + exhaustion).
demo-phase6:
	cd $(SIM_DIR) && uv sync --quiet
	cd $(SCAN_DIR) && uv sync --quiet
	cd $(BRIEF_DIR) && uv sync --quiet
	cd $(LAYOUT_DIR) && uv sync --quiet
	cd tests/e2e && DATABASE_URL=$(DATABASE_URL) pnpm vitest run phase6
	cd $(LAYOUT_DIR) && uv run python scripts/demo_phase6.py
	@echo "demo-phase6: merged plan SVG golden at fixtures/goldens/phase6_2br_mep.svg"

dev-up:
	docker compose up -d

dev-down:
	docker compose down
