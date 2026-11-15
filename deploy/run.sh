#!/usr/bin/env bash
# Launch the Earth Verdict API with a single worker so in-process rate limits
# and caches stay consistent. Reads standard env vars (PORT, OFFLINE,
# EV_DATA_DIR, EV_CORS_ORIGINS, EV_RATE_LIMIT_EXEMPT_LOCAL, GEMINI_API_KEY,
# EARTHDATA_TOKEN).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UVICORN="$ROOT/backend/.venv/bin/uvicorn"
if [[ ! -x "$UVICORN" ]]; then
  UVICORN="uvicorn"
fi

PORT="${PORT:-8790}"

exec "$UVICORN" app.main:app \
  --app-dir "$ROOT/backend" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --workers 1 \
  ${1+"$@"}
