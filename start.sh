#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.ctrl_panel.pid"
LOG_FILE="$ROOT_DIR/.ctrl_panel.log"
PORT="${FLASK_PORT:-5000}"

read_pid() {
    if [[ -f "$PID_FILE" ]]; then
        tr -dc '0-9' <"$PID_FILE"
    fi
}

is_running() {
    local pid="$1"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

pid_matches_app() {
    local pid="$1"
    local cmd cwd
    cmd="$(ps -p "$pid" -o cmd= 2>/dev/null || true)"
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    [[ "$cmd" == *"app.py"* && "$cwd" == "$ROOT_DIR" ]]
}

find_pid_by_port() {
    ss -ltnp 2>/dev/null | sed -n "s/.*:${PORT}[[:space:]].*pid=\\([0-9]\\+\\).*/\\1/p" | head -n 1
}

existing_pid="$(read_pid || true)"
if is_running "${existing_pid:-}"; then
    if pid_matches_app "$existing_pid"; then
        echo "ctrl_panel is already running (PID: $existing_pid)"
        echo "log: $LOG_FILE"
        exit 0
    fi
    echo "PID file points to non-app process ($existing_pid), cleaning up stale PID file"
    rm -f "$PID_FILE"
fi

port_pid="$(find_pid_by_port || true)"
if is_running "${port_pid:-}"; then
    if pid_matches_app "$port_pid"; then
        echo "$port_pid" >"$PID_FILE"
        echo "ctrl_panel is already running (PID: $port_pid)"
        echo "log: $LOG_FILE"
        exit 0
    fi
    echo "port $PORT is already in use by another process (PID: $port_pid)"
    ps -p "$port_pid" -o pid=,cmd= || true
    exit 1
fi

# 清理陈旧 PID 文件
rm -f "$PID_FILE"

cd "$ROOT_DIR"

nohup uv run python app.py >"$LOG_FILE" 2>&1 &
new_pid=$!
echo "$new_pid" >"$PID_FILE"

sleep 0.3
if ! is_running "$new_pid"; then
    echo "failed to start ctrl_panel"
    echo "last log lines:"
    tail -n 30 "$LOG_FILE" || true
    rm -f "$PID_FILE"
    exit 1
fi

ssl_mode="$(echo "${FLASK_SSL_MODE:-off}" | tr '[:upper:]' '[:lower:]')"
scheme="http"
if [[ "$ssl_mode" == "1" || "$ssl_mode" == "true" || "$ssl_mode" == "yes" || "$ssl_mode" == "on" || "$ssl_mode" == "adhoc" || "$ssl_mode" == "files" || "$ssl_mode" == "cert" || "$ssl_mode" == "certificate" ]]; then
    scheme="https"
fi

echo "ctrl_panel started"
echo "PID: $new_pid"
echo "URL: ${scheme}://127.0.0.1:${PORT}"
echo "log: $LOG_FILE"
