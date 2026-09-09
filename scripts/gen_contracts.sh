#!/usr/bin/env bash
# Generate JSON Schema and TypeScript from the pydantic source of truth.
# CI fails on drift: a hand-edited generated file is a build break.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p contracts/schema contracts/ts
.venv/bin/python -m scripts.emit_schema

if command -v npx >/dev/null 2>&1; then
  for f in contracts/schema/*.json; do
    npx --yes json-schema-to-typescript@15 "$f" \
      -o "contracts/ts/$(basename "${f%.json}").d.ts" --bannerComment "" 2>/dev/null || true
  done
else
  echo "npx not found — TypeScript types not regenerated" >&2
fi
echo "contracts generated"
