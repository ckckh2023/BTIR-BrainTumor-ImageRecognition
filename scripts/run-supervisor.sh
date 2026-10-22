#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIRECTORY="$PROJECT_ROOT/logs"
PID_FILE="$LOG_DIRECTORY/supervisor.pid"
LOCK_FILE="$LOG_DIRECTORY/supervisor.lock"

usage() {
    cat <<'EOF'
用法：
  bash scripts/run-supervisor.sh [Python解释器路径]

启动：
  source .venv/bin/activate
  bash scripts/run-supervisor.sh
EOF
}

fail() {
    if [[ "${CONSOLE_PID:-0}" -gt 0 ]]; then
        log "守护进程错误：$*"
    else
        printf '[BTIR] 守护进程错误：%s\n' "$*" >&2
    fi
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

[[ -x "$PYTHON_EXE" ]] || fail "找不到可执行的 Python 解释器：$PYTHON_EXE"
[[ -f "$PROJECT_ROOT/Main.py" ]] || fail "找不到项目入口：$PROJECT_ROOT/Main.py"

API_HOST="${BTIR_API_HOST:-0.0.0.0}"
API_PORT="${BTIR_API_PORT:-8000}"
RESTART_DELAY_SECONDS="${BTIR_SUPERVISOR_RESTART_DELAY_SECONDS:-10}"
HEALTH_CHECK_SECONDS="${BTIR_SUPERVISOR_HEALTH_CHECK_SECONDS:-15}"
WORKER_STARTUP_GRACE_SECONDS="${BTIR_SUPERVISOR_WORKER_STARTUP_GRACE_SECONDS:-120}"
TASK_RECONCILE_SECONDS="${BTIR_SUPERVISOR_TASK_RECONCILE_SECONDS:-60}"
RECONCILE_TIMEOUT_SECONDS="${BTIR_SUPERVISOR_RECONCILE_TIMEOUT_SECONDS:-120}"
SHUTDOWN_GRACE_SECONDS="${BTIR_SUPERVISOR_SHUTDOWN_GRACE_SECONDS:-300}"
API_FAILURE_THRESHOLD="${BTIR_SUPERVISOR_API_FAILURE_THRESHOLD:-3}"
API_STARTUP_GRACE_SECONDS="${BTIR_SUPERVISOR_API_STARTUP_GRACE_SECONDS:-60}"
case "$API_HOST" in
    0.0.0.0) VISIT_HOST=127.0.0.1 ;;
    ::|'[::]') VISIT_HOST='[::1]' ;;
    *:*) VISIT_HOST="[${API_HOST#[}]"; VISIT_HOST="${VISIT_HOST%]}]" ;;
    *) VISIT_HOST="$API_HOST" ;;
esac
HEALTH_BASE_URL="http://$VISIT_HOST:$API_PORT"

require_integer() {
    local name="$1"
    local value="$2"
    local minimum="$3"
    local maximum="$4"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < minimum || value > maximum )); then
        fail "$name 必须是 $minimum 到 $maximum 之间的整数"
    fi
}

require_integer "BTIR_API_PORT" "$API_PORT" 1 65535
require_integer "BTIR_SUPERVISOR_RESTART_DELAY_SECONDS" "$RESTART_DELAY_SECONDS" 1 300
require_integer "BTIR_SUPERVISOR_HEALTH_CHECK_SECONDS" "$HEALTH_CHECK_SECONDS" 5 300
require_integer "BTIR_SUPERVISOR_WORKER_STARTUP_GRACE_SECONDS" "$WORKER_STARTUP_GRACE_SECONDS" 1 600
require_integer "BTIR_SUPERVISOR_TASK_RECONCILE_SECONDS" "$TASK_RECONCILE_SECONDS" 10 3600
require_integer "BTIR_SUPERVISOR_RECONCILE_TIMEOUT_SECONDS" "$RECONCILE_TIMEOUT_SECONDS" 10 3600
require_integer "BTIR_SUPERVISOR_SHUTDOWN_GRACE_SECONDS" "$SHUTDOWN_GRACE_SECONDS" 1 3600
require_integer "BTIR_SUPERVISOR_API_STARTUP_GRACE_SECONDS" "$API_STARTUP_GRACE_SECONDS" 1 600
require_integer "BTIR_SUPERVISOR_API_FAILURE_THRESHOLD" "$API_FAILURE_THRESHOLD" 1 20

mkdir -p "$LOG_DIRECTORY"

CONSOLE_PID=0
CONSOLE_EVENTS=""
current_status=""
api_pid=0
worker_pid=0
worker_started_at=0
api_started_at=0
api_seen_healthy=false
page_announced=false
services_ready=false
api_health_failures=0

log() {
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S') [守护进程] $*"
    printf '%s\n' "$line" >>"$LOG_DIRECTORY/supervisor.log"
    if [[ "$CONSOLE_PID" -gt 0 ]]; then
        printf '%s\n' "$line" >>"$CONSOLE_EVENTS"
        if ! kill -0 "$CONSOLE_PID" 2>/dev/null; then
            printf '%s\n' "$line"
        fi
    else
        printf '%s\n' "$line"
    fi
}

set_status() {
    if [[ "$current_status" != "$*" ]]; then
        current_status="$*"
        log "[状态] $*"
    fi
}

if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        fail "已有 BTIR 守护进程正在运行"
    fi
elif [[ -f "$PID_FILE" ]]; then
    existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
        fail "已有 BTIR 守护进程正在运行（进程号=$existing_pid）"
    fi
fi

process_is_running() {
    local pid="$1"
    [[ "$pid" -gt 0 ]] && kill -0 "$pid" 2>/dev/null
}

start_api() {
    set_status "正在启动 API 服务"
    (
        cd "$PROJECT_ROOT"
        exec 9>&-
        exec "$PYTHON_EXE" -u -m uvicorn api.app:app --host "$API_HOST" --port "$API_PORT"
    ) >>"$LOG_DIRECTORY/api.stdout.log" 2>>"$LOG_DIRECTORY/api.stderr.log" &
    api_pid=$!
    api_started_at="$(date +%s)"
    api_seen_healthy=false
    page_announced=false
    services_ready=false
}

start_worker() {
    set_status "正在启动 3D 推理进程"
    (
        cd "$PROJECT_ROOT"
        exec 9>&-
        exec "$PYTHON_EXE" -u -m workers.run_worker
    ) >>"$LOG_DIRECTORY/worker.stdout.log" 2>>"$LOG_DIRECTORY/worker.stderr.log" &
    worker_pid=$!
    services_ready=false
    worker_started_at="$(date +%s)"
}

stop_process() {
    local pid="$1"
    local name="$2"
    if ! process_is_running "$pid"; then
        return
    fi

    set_status "正在停止 $name"
    kill -TERM "$pid" 2>/dev/null || true
    for ((second = 0; second < SHUTDOWN_GRACE_SECONDS; second++)); do
        process_is_running "$pid" || break
        sleep 1
    done
    if process_is_running "$pid"; then
        log "$name 在 ${SHUTDOWN_GRACE_SECONDS} 秒宽限期后仍未退出，正在强制停止"
        kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
}

restart_api() {
    stop_process "$api_pid" 'API 服务'
    sleep "$RESTART_DELAY_SECONDS"
    start_api
    api_health_failures=0
}

restart_worker() {
    stop_process "$worker_pid" '3D 推理进程'
    sleep "$RESTART_DELAY_SECONDS"
    start_worker
}

http_status() {
    curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 3 "$1" 2>/dev/null ||
        true
}

http_body() {
    curl --noproxy '*' -sS --max-time 3 "$1" 2>/dev/null || true
}

run_task_reconciliation() {
    local reconcile_log="$LOG_DIRECTORY/reconcile.log"
    if command -v timeout >/dev/null 2>&1; then
        if ! timeout "$RECONCILE_TIMEOUT_SECONDS" \
            "$PYTHON_EXE" "$PROJECT_ROOT/Main.py" reconcile-tasks \
            >>"$reconcile_log" 2>&1; then
            log '任务状态巡检失败或超时'
        fi
    elif ! "$PYTHON_EXE" "$PROJECT_ROOT/Main.py" reconcile-tasks \
        >>"$reconcile_log" 2>&1; then
        log '任务状态巡检失败'
    fi
}

cleanup() {
    trap - EXIT INT TERM
    stop_process "$worker_pid" '3D 推理进程'
    stop_process "$api_pid" 'API 服务'
    if [[ -f "$PID_FILE" && "$(cat "$PID_FILE" 2>/dev/null || true)" == "$$" ]]; then
        rm -f "$PID_FILE"
    fi
    log '守护进程已停止'
    if [[ "$CONSOLE_PID" -gt 0 ]]; then
        kill -TERM "$CONSOLE_PID" 2>/dev/null || true
        wait "$CONSOLE_PID" 2>/dev/null || true
        rm -f "$CONSOLE_EVENTS" "$CONSOLE_EVENTS.ready"
    fi
}

trap 'exit 0' INT TERM
trap cleanup EXIT

CONSOLE_EVENTS="$(mktemp "$LOG_DIRECTORY/.console.XXXXXX")"
touch "$LOG_DIRECTORY/worker.stdout.log" "$LOG_DIRECTORY/worker.stderr.log"
(
    exec 9>&-
    exec "$PYTHON_EXE" -u "$PROJECT_ROOT/scripts/supervisor_console.py" \
        "$CONSOLE_EVENTS" "$LOG_DIRECTORY" "$$" \
        "$(wc -c <"$LOG_DIRECTORY/worker.stdout.log")" \
        "$(wc -c <"$LOG_DIRECTORY/worker.stderr.log")"
) 2>>"$LOG_DIRECTORY/startup.log" &
CONSOLE_PID=$!
for ((attempt = 0; attempt < 100; attempt++)); do
    [[ -f "$CONSOLE_EVENTS.ready" ]] && break
    process_is_running "$CONSOLE_PID" || break
    sleep 0.05
done
if [[ ! -f "$CONSOLE_EVENTS.ready" ]]; then
    fail '终端状态显示器启动失败，详情见 logs/startup.log'
fi
set_status '[1/4] 正在检查 Python 3.11'
if ! "$PYTHON_EXE" -c \
    'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)'; then
    fail "BTIR 需要 Python 3.11，请检查解释器：$PYTHON_EXE"
fi

set_status '[2/4] 正在检查项目依赖'
if ! (
    cd "$PROJECT_ROOT"
    "$PYTHON_EXE" -c \
        'import fastapi, pydantic, redis, rq, uvicorn, jose, passlib, PIL, nibabel, numpy, einops, monai, torch, transformers, tqdm, multipart'
) >>"$LOG_DIRECTORY/startup.log" 2>&1; then
    fail "项目依赖不完整，请执行：$PYTHON_EXE -m pip install -r requirements.txt"
fi

set_status "[3/4] 正在检查 API 端口 $API_PORT"
if "$PYTHON_EXE" -c \
    'import socket, sys; s=socket.socket(); s.settimeout(1); code=s.connect_ex(("127.0.0.1", int(sys.argv[1]))); s.close(); raise SystemExit(0 if code == 0 else 1)' \
    "$API_PORT"; then
    fail "API 端口 $API_PORT 已被占用"
fi

set_status '[4/4] 正在检查 Redis 连接'
if (
    cd "$PROJECT_ROOT"
    "$PYTHON_EXE" -c \
        'from core.settings import SETTINGS; from redis import Redis; Redis.from_url(SETTINGS.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()'
) >>"$LOG_DIRECTORY/startup.log" 2>&1; then
    :
else
    log 'Redis 连接失败，正在重试'
fi


printf '%s\n' "$$" >"$PID_FILE"

health_checks_enabled=true
if ! command -v curl >/dev/null 2>&1; then
    health_checks_enabled=false
    log 'curl 未安装，健康检查已禁用'
    log "访问地址：$HEALTH_BASE_URL/web/"
fi


start_api
start_worker

now="$(date +%s)"
next_health_check="$now"
next_task_reconcile=$((now + TASK_RECONCILE_SECONDS))

while true; do
    if ! process_is_running "$api_pid"; then
        exit_code=0
        wait "$api_pid" 2>/dev/null || exit_code=$?
        log "API 已退出，退出码=$exit_code，将在 ${RESTART_DELAY_SECONDS} 秒后重启"
        sleep "$RESTART_DELAY_SECONDS"
        start_api
        api_health_failures=0
    fi

    if ! process_is_running "$worker_pid"; then
        exit_code=0
        wait "$worker_pid" 2>/dev/null || exit_code=$?
        log "3D 推理进程已退出，退出码=$exit_code，将在 ${RESTART_DELAY_SECONDS} 秒后重启"
        sleep "$RESTART_DELAY_SECONDS"
        start_worker
    fi

    now="$(date +%s)"
    if [[ "$health_checks_enabled" == true && "$now" -ge "$next_health_check" ]]; then
        next_health_check=$((now + HEALTH_CHECK_SECONDS))
        if (( now - api_started_at < API_STARTUP_GRACE_SECONDS )) && [[ "$services_ready" == false ]]; then
            next_health_check=$((now + 1))
        fi
        if [[ "$(http_status "$HEALTH_BASE_URL/healthz")" == '200' ]]; then
            api_health_failures=0
            api_seen_healthy=true
            if [[ "$page_announced" == false ]]; then
                log "访问地址：$HEALTH_BASE_URL/web/"
                log "API 文档：$HEALTH_BASE_URL/docs"
                page_announced=true
            fi
        elif [[ "$api_seen_healthy" == true ]] || (( now - api_started_at >= API_STARTUP_GRACE_SECONDS )); then
            api_health_failures=$((api_health_failures + 1))
            log "API 健康检查失败（连续失败次数=$api_health_failures，详情见 api.stderr.log）"
            if [[ "$api_health_failures" -ge "$API_FAILURE_THRESHOLD" ]]; then
                restart_api
                continue
            fi
        fi

        readiness_body="$(http_body "$HEALTH_BASE_URL/readyz")"
        if [[ "$api_seen_healthy" == true ]] &&
            grep -qE '"status"[[:space:]]*:[[:space:]]*"ready"' <<<"$readiness_body"; then
            if [[ "$services_ready" == false ]]; then
                log '服务已就绪'
                set_status '运行中'
                services_ready=true
            fi
        elif [[ "$page_announced" == true ]]; then
            services_ready=false
            waiting_for=()
            for component in redis inference_worker models task_database; do
                if grep -qE "\"$component\"[[:space:]]*:[[:space:]]*\"unavailable\"" <<<"$readiness_body"; then
                    case "$component" in
                        redis) waiting_for+=('Redis') ;;
                        inference_worker) waiting_for+=('推理进程') ;;
                        models) waiting_for+=('模型文件') ;;
                        task_database) waiting_for+=('任务数据库') ;;
                    esac
                fi
            done
            set_status "等待推理服务：${waiting_for[*]:-正在检查}"
        fi
        if
            grep -qE '"redis"[[:space:]]*:[[:space:]]*"ok"' <<<"$readiness_body" &&
            grep -qE '"inference_worker"[[:space:]]*:[[:space:]]*"unavailable"' <<<"$readiness_body" &&
            (( now - worker_started_at >= WORKER_STARTUP_GRACE_SECONDS )); then
            log '3D 推理进程尚未注册，正在重启'
            restart_worker
        fi
    fi

    if [[ "$now" -ge "$next_task_reconcile" ]]; then
        next_task_reconcile=$((now + TASK_RECONCILE_SECONDS))
        run_task_reconciliation
    fi

    sleep 1
done
