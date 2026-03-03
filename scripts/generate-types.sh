#!/usr/bin/env bash
# generate-types.sh — Generate TypeScript types from FastAPI OpenAPI spec
# Requires the backend to be running: ./scripts/setup-dev.sh

set -euo pipefail

echo "→ Generating TypeScript types from OpenAPI spec..."
cd frontend
npx openapi-typescript http://localhost:8000/api/openapi.json -o src/types/api.ts
echo "✓ Types written to frontend/src/types/api.ts"
