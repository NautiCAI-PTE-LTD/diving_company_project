#!/usr/bin/env bash
# Start NautiCAI backend (GPU) + ensure nginx serves the built UI.
# Run in one terminal, or use systemd units for production.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/backend/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/backend/.env"
  set +a
fi
export NAUTICAI_USE_SQLITE="${NAUTICAI_USE_SQLITE:-1}"
export NAUTICAI_DEVICE="${NAUTICAI_DEVICE:-cuda}"
export NAUTICAI_FP16="${NAUTICAI_FP16:-1}"
export NAUTICAI_MATMUL="${NAUTICAI_MATMUL:-high}"
export NAUTICAI_ANALYZE_CONCURRENCY="${NAUTICAI_ANALYZE_CONCURRENCY:-1}"

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "Building frontend (first time)…"
  (cd "$ROOT/frontend" && npm install && npm run build)
fi

if ! curl -sf --max-time 2 http://127.0.0.1/api/health >/dev/null 2>&1; then
  if command -v nginx >/dev/null; then
    sudo nginx -t 2>/dev/null && sudo systemctl reload nginx 2>/dev/null || true
  fi
fi

echo "Starting backend on :8000 (device=$NAUTICAI_DEVICE, sqlite=$NAUTICAI_USE_SQLITE)…"
echo "UI: http://$(hostname -I | awk '{print $1}')/"
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
