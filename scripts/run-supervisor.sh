#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: bash scripts/run-supervisor.sh /path/to/venv/bin/python" >&2
    exit 2
fi

PYTHON_EXE="$1"
API_PORT="${BTIR_API_PORT:-8000}"
RESTART_DELAY_SECONDS="${BTIR_SUPERVISOR_RESTART_DELAY_SECONDS:-10}"
HEALTH_CHECK_SECONDS="${BTIR_SUPERVISOR_HEALTH_CHECK_SECONDS:-15}"
WORKER_STARTUP_GRACE_SECONDS="${BTIR_SUPERVISOR_WORKER_STARTUP_GRACE_SECONDS:-30}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIRECTORY="$PROJECT_ROOT/logs"

if [[ ! -x "$PYTHON_EXE" ]]; then
    echo "Python executable not found or not executable: $PYTHON_EXE" >&2
    exit 2
fi

mkdir -p "$LOG_DIRECTORY"

log() {
    printf '%s [supervisor] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_DIRECTORY/supervisor.log"
}

start_api() {
    log 'starting api'
    (
        cd "$PROJECT_ROOT"
        exec "$PYTHON_EXE" -m uvicorn api.app:app --host 127.0.0.1 --port "$API_PORT"
    ) >>"$LOG_DIRECTORY/api.stdout.log" 2>>"$LOG_DIRECTORY/api.stderr.log" &
    api_pid=$!
}

start_worker() {
    log 'starting worker'
    (
        cd "$PROJECT_ROOT"
        exec "$PYTHON_EXE" -m workers.run_worker
    ) >>"$LOG_DIRECTORY/worker.stdout.log" 2>>"$LOG_DIRECTORY/worker.stderr.log" &
    worker_pid=$!
    worker_started_at="$(date +%s)"
}

stop_process() {
    local pid="$1"
    local name="$2"
    if [[ "$pid" -le 0 ]]; then
        return
    fi
    if kill -0 "$pid" 2>/dev/null; then
        log "stopping $name (pid=$pid)"
        kill "$pid" 2>/dev/null || true
        for _ in {1..10}; do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
            log "force stopping $name (pid=$pid)"
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
    wait "$pid" 2>/dev/null || true
}

restart_api() {
    stop_process "$api_pid" 'api'
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
    curl -sS -o /dev/null -w '%{http_code}' --max-time 3 "$1" || printf '000'
}

http_body() {
    curl -sS --max-time 3 "$1" || true
}

health_checks_enabled=true
if ! command -v curl >/dev/null 2>&1; then
    health_checks_enabled=false
    log 'curl is unavailable; only process-exit restart checks are enabled'
fi

api_pid=0
worker_pid=0
worker_started_at=0
api_health_failures=0
next_health_check=0

cleanup() {
    trap - EXIT INT TERM
    stop_process "$worker_pid" 'worker'
    stop_process "$api_pid" 'api'
}
trap cleanup EXIT INT TERM

start_api
start_worker

while true; do
    if ! kill -0 "$api_pid" 2>/dev/null; then
        wait "$api_pid" 2>/dev/null || exit_code=$?
        log "api exited with code ${exit_code:-unknown}; restarting in $RESTART_DELAY_SECONDS seconds"
        sleep "$RESTART_DELAY_SECONDS"
        start_api
        api_health_failures=0
    fi

    if ! kill -0 "$worker_pid" 2>/dev/null; then
        wait "$worker_pid" 2>/dev/null || exit_code=$?
        log "worker exited with code ${exit_code:-unknown}; restarting in $RESTART_DELAY_SECONDS seconds"
        sleep "$RESTART_DELAY_SECONDS"
        start_worker
    fi

    now="$(date +%s)"
    if [[ "$health_checks_enabled" == true && "$now" -ge "$next_health_check" ]]; then
        next_health_check=$((now + HEALTH_CHECK_SECONDS))
        if [[ "$(http_status "http://127.0.0.1:$API_PORT/healthz")" == '200' ]]; then
            api_health_failures=0
        else
            api_health_failures=$((api_health_failures + 1))
            log "api health check failed (failures=$api_health_failures)"
            if [[ "$api_health_failures" -ge 3 ]]; then
                restart_api
            fi
        fi

        readiness_body="$(http_body "http://127.0.0.1:$API_PORT/readyz")"
        queue_body="$(http_body "http://127.0.0.1:$API_PORT/ops/queue")"
        if
            grep -qE '"redis"[[:space:]]*:[[:space:]]*"ok"' <<<"$readiness_body" &&
            grep -qE '"inference_worker"[[:space:]]*:[[:space:]]*"unavailable"' <<<"$readiness_body" &&
            grep -qE '"running_jobs"[[:space:]]*:[[:space:]]*0' <<<"$queue_body" &&
            (( now - worker_started_at >= WORKER_STARTUP_GRACE_SECONDS )); then
            log 'worker is not registered and no job is running; restarting worker'
            restart_worker
        fi
    fi

    sleep 1
done
