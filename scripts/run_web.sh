#!/usr/bin/env bash
# Starts the Django Ninja API (backend/, port 8000) and the Next.js UI (port 3000) in the
# background, each unless its port is already in use. Intended for cron at boot:
#   @reboot sleep 30 && /path/to/attendance_system/scripts/run_web.sh
# The UI must have been built once: cd frontend && npm ci && npm run build
set -u

API_PORT=8000
UI_PORT=3000
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

listening() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

if ! listening "$API_PORT"; then
    cd "$PROJECT_DIR/backend" || exit 1
    nohup "$PROJECT_DIR/backend/.venv/bin/python" "$PROJECT_DIR/backend/manage.py" web --port "$API_PORT" \
        >> "$LOG_DIR/web.log" 2>&1 &
fi

if ! listening "$UI_PORT"; then
    # cron has no login shell, so load nvm to find node.
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    # shellcheck disable=SC1091
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
    cd "$PROJECT_DIR/frontend" || exit 1
    NEXT_TELEMETRY_DISABLED=1 nohup "$PROJECT_DIR/frontend/node_modules/.bin/next" start --port "$UI_PORT" \
        >> "$LOG_DIR/frontend.log" 2>&1 &
fi
