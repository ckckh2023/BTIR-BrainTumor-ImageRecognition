#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIRECTORY="$PROJECT_ROOT/logs"
PID_FILE="$LOG_DIRECTORY/supervisor.pid"
LOCK_FILE="$LOG_DIRECTORY/supervisor.lock"

usage() {
    cat <<'EOF'
Usage:
  bash scripts/run-supervisor.sh [python-executable]

Python lookup order:
  1. command argument
  2. BTIR_PYTHON_EXE
  3. active VIRTUAL_ENV
  4. <project>/.venv/bin/python
EOF
}

fail() {
    printf '[BTIR] supervisor error: %s\n' "$*" >&2
    exit 2
}

if [[ $# -gt 1 ]]; then
    usage >&2
    exit 2
fi

if [[ $# -eq 1 ]]; then
    PYTHON_EXE="$1"
elif [[ -n "${BTIR_PYTHON_EXE:-}" ]]; then
    PYTHON_EXE="$BTIR_PYTHON_EXE"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    PYTHON_EXE="$VIRTUAL_ENV/bin/python"
else
    PYTHON_EXE="$PROJECT_ROOT/.venv/bin/python"
fi

[[ -x "$PYTHON_EXE" ]] || fail "Python executable not found: $PYTHON_EXE"
[[ -f "$PROJECT_ROOT/Main.py" ]] || fail "project entry not found: $PROJECT_ROOT/Main.py"

API_HOST="${BTIR_API_HOST:-127.0.0.1}"
API_PORT="${BTIR_API_PORT:-8000}"
RESTART_DELAY_SECONDS="${BTIR_SUPERVISOR_RESTART_DELAY_SECONDS:-10}"
HEALTH_CHECK_SECONDS="${BTIR_SUPERVISOR_HEALTH_CHECK_SECONDS:-15}"
WORKER_STARTUP_GRACE_SECONDS="${BTIR_SUPERVISOR_WORKER_STARTUP_GRACE_SECONDS:-120}"
TASK_RECONCILE_SECONDS="${BTIR_SUPERVISOR_TASK_RECONCILE_SECONDS:-60}"
RECONCILE_TIMEOUT_SECONDS="${BTIR_SUPERVISOR_RECONCILE_TIMEOUT_SECONDS:-120}"
SHUTDOWN_GRACE_SECONDS="${BTIR_SUPERVISOR_SHUTDOWN_GRACE_SECONDS:-300}"
API_FAILURE_THRESHOLD="${BTIR_SUPERVISOR_API_FAILURE_THRESHOLD:-3}"
HEALTH_BASE_URL="http://127.0.0.1:$API_PORT"

require_integer() {
    local name="$1"
    local value="$2"
    local minimum="$3"
    local maximum="$4"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < minimum || value > maximum )); then
        fail "$name must be an integer between $minimum and $maximum"
    fi
}

require_integer "BTIR_API_PORT" "$API_PORT" 1 65535
require_integer "BTIR_SUPERVISOR_RESTART_DELAY_SECONDS" "$RESTART_DELAY_SECONDS" 1 300
require_integer "BTIR_SUPERVISOR_HEALTH_CHECK_SECONDS" "$HEALTH_CHECK_SECONDS" 5 300
require_integer "BTIR_SUPERVISOR_WORKER_STARTUP_GRACE_SECONDS" "$WORKER_STARTUP_GRACE_SECONDS" 1 600
require_integer "BTIR_SUPERVISOR_TASK_RECONCILE_SECONDS" "$TASK_RECONCILE_SECONDS" 10 3600
require_integer "BTIR_SUPERVISOR_RECONCILE_TIMEOUT_SECONDS" "$RECONCILE_TIMEOUT_SECONDS" 10 3600
require_integer "BTIR_SUPERVISOR_SHUTDOWN_GRACE_SECONDS" "$SHUTDOWN_GRACE_SECONDS" 1 3600
require_integer "BTIR_SUPERVISOR_API_FAILURE_THRESHOLD" "$API_FAILURE_THRESHOLD" 1 20

mkdir -p "$LOG_DIRECTORY"

log() {
    printf '%s [supervisor] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" |
        tee -a "$LOG_DIRECTORY/supervisor.log"
}

if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        fail "another BTIR supervisor is already running"
    fi
elif [[ -f "$PID_FILE" ]]; then
    existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
        fail "another BTIR supervisor is already running (pid=$existing_pid)"
    fi
fi

if ! "$PYTHON_EXE" -c \
    'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)'; then
    fail "BTIR requires Python 3.11: $PYTHON_EXE"
fi

if ! (
    cd "$PROJECT_ROOT"
    "$PYTHON_EXE" -c 'import fastapi, redis, rq, uvicorn'
); then
    fail "project dependencies are incomplete; run: $PYTHON_EXE -m pip install -r requirements.txt"
fi

if "$PYTHON_EXE" -c \
    'import socket, sys; s=socket.socket(); s.settimeout(1); code=s.connect_ex(("127.0.0.1", int(sys.argv[1]))); s.close(); raise SystemExit(0 if code == 0 else 1)' \
    "$API_PORT"; then
    fail "API port $API_PORT is already in use"
fi

if (
    cd "$PROJECT_ROOT"
    "$PYTHON_EXE" -c \
        'from core.settings import SETTINGS; from redis import Redis; Redis.from_url(SETTINGS.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()'
); then
    log 'Redis connection is ready'
else
    log 'Redis is unavailable at startup; API will report not ready and the supervisor will keep restarting the worker'
fi

printf '%s\n' "$$" >"$PID_FILE"

api_pid=0
worker_pid=0
worker_started_at=0
api_health_failures=0

process_is_running() {
    local pid="$1"
    [[ "$pid" -gt 0 ]] && kill -0 "$pid" 2>/dev/null
}

start_api() {
    log "starting API on $API_HOST:$API_PORT"
    (
        cd "$PROJECT_ROOT"
        exec 9>&-
        exec "$PYTHON_EXE" -m uvicorn api.app:app --host "$API_HOST" --port "$API_PORT"
    ) >>"$LOG_DIRECTORY/api.stdout.log" 2>>"$LOG_DIRECTORY/api.stderr.log" &
    api_pid=$!
}

start_worker() {
    log 'starting inference worker'
    (
        cd "$PROJECT_ROOT"
        exec 9>&-
        exec "$PYTHON_EXE" -m workers.run_worker
    ) >>"$LOG_DIRECTORY/worker.stdout.log" 2>>"$LOG_DIRECTORY/worker.stderr.log" &
    worker_pid=$!
    worker_started_at="$(date +%s)"
}

stop_process() {
    local pid="$1"
    local name="$2"
    if ! process_is_running "$pid"; then
        return
    fi

    log "stopping $name (pid=$pid)"
    kill -TERM "$pid" 2>/dev/null || true
    for ((second = 0; second < SHUTDOWN_GRACE_SECONDS; second++)); do
        process_is_running "$pid" || break
        sleep 1
    done
    if process_is_running "$pid"; then
        log "force stopping $name after ${SHUTDOWN_GRACE_SECONDS}s grace period"
        kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
}

restart_api() {
    stop_process "$api_pid" 'API'
    sleep "$RESTART_DELAY_SECONDS"
    start_api
    api_health_failures=0
}

restart_worker() {
    stop_process "$worker_pid" 'worker'
    sleep "$RESTART_DELAY_SECONDS"
    start_worker
}

http_status() {
    curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "$1" 2>/dev/null ||
        printf '000'
}

http_body() {
    curl -sS --max-time 3 "$1" 2>/dev/null || true
}

run_task_reconciliation() {
    local reconcile_log="$LOG_DIRECTORY/reconcile.log"
    if command -v timeout >/dev/null 2>&1; then
        if ! timeout "$RECONCILE_TIMEOUT_SECONDS" \
            "$PYTHON_EXE" "$PROJECT_ROOT/Main.py" reconcile-tasks \
            >>"$reconcile_log" 2>&1; then
            log 'task reconciliation failed or timed out'
        fi
    elif ! "$PYTHON_EXE" "$PROJECT_ROOT/Main.py" reconcile-tasks \
        >>"$reconcile_log" 2>&1; then
        log 'task reconciliation failed'
    fi
}

cleanup() {
    trap - EXIT INT TERM
    stop_process "$worker_pid" 'worker'
    stop_process "$api_pid" 'API'
    if [[ -f "$PID_FILE" && "$(cat "$PID_FILE" 2>/dev/null || true)" == "$$" ]]; then
        rm -f "$PID_FILE"
    fi
    log 'supervisor stopped'
}

trap 'exit 0' INT TERM
trap cleanup EXIT

health_checks_enabled=true
if ! command -v curl >/dev/null 2>&1; then
    health_checks_enabled=false
    log 'curl is unavailable; process-exit monitoring remains enabled'
fi

log "project root: $PROJECT_ROOT"
log "Python: $PYTHON_EXE"
log "logs: $LOG_DIRECTORY"

start_api
start_worker

now="$(date +%s)"
next_health_check="$now"
next_task_reconcile=$((now + TASK_RECONCILE_SECONDS))

while true; do
    if ! process_is_running "$api_pid"; then
        exit_code=0
        wait "$api_pid" 2>/dev/null || exit_code=$?
        log "API exited with code $exit_code; restarting in ${RESTART_DELAY_SECONDS}s"
        sleep "$RESTART_DELAY_SECONDS"
        start_api
        api_health_failures=0
    fi

    if ! process_is_running "$worker_pid"; then
        exit_code=0
        wait "$worker_pid" 2>/dev/null || exit_code=$?
        log "worker exited with code $exit_code; restarting in ${RESTART_DELAY_SECONDS}s"
        sleep "$RESTART_DELAY_SECONDS"
        start_worker
    fi

    now="$(date +%s)"
    if [[ "$health_checks_enabled" == true && "$now" -ge "$next_health_check" ]]; then
        next_health_check=$((now + HEALTH_CHECK_SECONDS))
        if [[ "$(http_status "$HEALTH_BASE_URL/healthz")" == '200' ]]; then
            api_health_failures=0
        else
            api_health_failures=$((api_health_failures + 1))
            log "API health check failed (failures=$api_health_failures)"
            if [[ "$api_health_failures" -ge "$API_FAILURE_THRESHOLD" ]]; then
                restart_api
            fi
        fi

        readiness_body="$(http_body "$HEALTH_BASE_URL/readyz")"
        queue_body="$(http_body "$HEALTH_BASE_URL/ops/queue")"
        if
            grep -qE '"redis"[[:space:]]*:[[:space:]]*"ok"' <<<"$readiness_body" &&
            grep -qE '"inference_worker"[[:space:]]*:[[:space:]]*"unavailable"' <<<"$readiness_body" &&
            grep -qE '"running_jobs"[[:space:]]*:[[:space:]]*0' <<<"$queue_body" &&
            (( now - worker_started_at >= WORKER_STARTUP_GRACE_SECONDS )); then
            log 'worker is not registered and no job is running; restarting worker'
            restart_worker
        fi
    fi

    if [[ "$now" -ge "$next_task_reconcile" ]]; then
        next_task_reconcile=$((now + TASK_RECONCILE_SECONDS))
        run_task_reconciliation
    fi

    sleep 1
done
