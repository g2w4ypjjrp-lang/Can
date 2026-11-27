#!/usr/bin/env bash
# Tüm testler: backend (gerçek PostgreSQL + RLS), frontend birim testleri, tip kontrolü ve derleme.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && uv run ruff check . && uv run pytest -q)
(cd frontend && npm test && npm run typecheck && npm run build)
