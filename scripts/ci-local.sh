#!/bin/bash
# Mirror the CI quality pipeline locally (.github/workflows/test.yml).
# Usage: ./scripts/ci-local.sh
# ponytail: single script instead of test-changed.sh/burn-in.sh trio —
# burn-in lives in the workflow; add more scripts when someone needs them.

set -e
cd "$(dirname "$0")/.."

echo "── lint-backend (ruff) ──────────────────────"
uv run ruff check .

echo "── lint-frontend (tsc) ──────────────────────"
(cd frontend && npx tsc -b)

echo "── test-backend (pytest) ────────────────────"
# Same dummy Langfuse env CI uses; port 9 makes the OTEL exporter fail fast.
YTFLOW_LANGFUSE_HOST=http://localhost:9 \
YTFLOW_LANGFUSE_PUBLIC_KEY=pk-ci \
YTFLOW_LANGFUSE_SECRET_KEY=sk-ci \
  uv run pytest -q

echo "── test-frontend (vitest) ───────────────────"
(cd frontend && npm test)

echo "✅ All CI stages passed locally"
