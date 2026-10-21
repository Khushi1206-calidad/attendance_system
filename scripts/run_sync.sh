#!/usr/bin/env bash
# Device-to-PostgreSQL sync for cron. Run it every minute:
#   * * * * * /path/to/attendance_system/scripts/run_sync.sh
# Each run first checks that the device is reachable on the network:
#   - unreachable (machine off the office network, device off): skip quietly;
#   - just became reachable (boot, reconnect): sync immediately;
#   - otherwise: sync once every SYNC_INTERVAL_SECONDS.
# Overlapping runs are rejected by the database advisory lock (exit code 3).
set -u

SYNC_INTERVAL_SECONDS=${SYNC_INTERVAL_SECONDS:-300}

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
ENV_FILE="$BACKEND_DIR/.env"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/sync.log"
STATE_FILE="$LOG_DIR/.device_state"
LAST_SUCCESS_FILE="$LOG_DIR/.last_success"
mkdir -p "$LOG_DIR"

log() { echo "$(date -Is) $*" >> "$LOG_FILE"; }
env_value() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '\r'; }

DEVICE_IP=$(env_value ATTENDANCE_DEVICE_IP)
DEVICE_PORT=$(env_value ATTENDANCE_DEVICE_PORT)
DEVICE_PORT=${DEVICE_PORT:-4370}

previous_state=$(cat "$STATE_FILE" 2>/dev/null || echo unknown)

# pyzk uses TCP by default; a 3-second connect attempt is enough to tell.
if ! timeout 3 bash -c "</dev/tcp/$DEVICE_IP/$DEVICE_PORT" 2>/dev/null; then
    if [ "$previous_state" != offline ]; then
        log "device $DEVICE_IP:$DEVICE_PORT unreachable; waiting for it to come back"
    fi
    echo offline > "$STATE_FILE"
    exit 0
fi
echo online > "$STATE_FILE"

now=$(date +%s)
last_success=$(cat "$LAST_SUCCESS_FILE" 2>/dev/null || echo 0)
if [ "$previous_state" = online ] && [ $((now - last_success)) -lt $((SYNC_INTERVAL_SECONDS - 10)) ]; then
    exit 0
fi
if [ "$previous_state" != online ]; then
    log "device $DEVICE_IP:$DEVICE_PORT reachable; syncing now"
fi

cd "$BACKEND_DIR" || exit 1
"$BACKEND_DIR/.venv/bin/python" "$BACKEND_DIR/manage.py" \
    sync --mode scheduled >> "$LOG_FILE" 2>&1
status=$?
case "$status" in
    0) echo "$now" > "$LAST_SUCCESS_FILE" ;;
    3) ;;  # another sync is already running
    *) log "sync exited with code $status; retrying next minute" ;;
esac
exit "$status"
