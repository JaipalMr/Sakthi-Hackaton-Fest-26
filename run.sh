#!/usr/bin/env bash
# One-command start for macOS/Linux: sets up on first run, then starts backend + frontend.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
# marker file: a half-finished install is redone instead of being trusted
if [ ! -f .venv/.deps_ok ]; then
  [ -d .venv ] || "$PY" -m venv .venv
  . .venv/bin/activate
  python -m pip install -r requirements.txt
  touch .venv/.deps_ok
fi
. .venv/bin/activate
[ -d frontend/node_modules/.bin ] || (cd frontend && npm install)
echo "Starting backend (first start can take about a minute while the model is prepared)..."
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 &
BE=$!; trap 'kill $BE 2>/dev/null' EXIT
tries=0
until curl -sf http://127.0.0.1:8000/api/health >/dev/null; do
  kill -0 $BE 2>/dev/null || { echo "The backend stopped - see the error above."; exit 1; }
  tries=$((tries+1)); [ $tries -ge 90 ] && { echo "Backend not ready after 3 minutes."; exit 1; }
  sleep 2
done
echo "Backend ready. Starting frontend on http://127.0.0.1:5173"
cd frontend && npm run dev
