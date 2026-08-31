#!/usr/bin/env bash
# Regenerates src/chapter_contracts/generated/*.py from packages/contracts/schemas/*.json.
# Pinned generator: datamodel-code-generator (see pyproject dev group). Run via `make codegen`.
set -euo pipefail
cd "$(dirname "$0")/.."
GEN=src/chapter_contracts/generated
mkdir -p "$GEN"

gen() {
  uv run datamodel-codegen \
    --input "../schemas/$1" \
    --input-file-type jsonschema \
    --output "$GEN/$2" \
    --output-model-type pydantic_v2.BaseModel \
    --base-class chapter_contracts.strict.StrictBaseModel \
    --use-standard-collections \
    --use-union-operator \
    --field-constraints \
    --use-annotated \
    --disable-timestamp \
    --target-python-version 3.12
  echo "generated $GEN/$2"
}

gen chapter-layout.v2.3.json chapter_layout.py
gen brief.v1.json brief.py
gen command-envelope.v1.json command_envelope.py
gen wss-messages.v1.json wss_messages.py

cat > "$GEN/__init__.py" <<'EOF'
# GENERATED package — see scripts/codegen.sh. DO NOT EDIT.
EOF
