#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT_DIR/.ctrl_panel.pid"
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

pid="$(read_pid || true)"

if ! is_running "${pid:-}"; then
    port_pid="$(find_pid_by_port || true)"
    if is_running "${port_pid:-}" && pid_matches_app "$port_pid"; then
        pid="$port_pid"
    else
        rm -f "$PID_FILE"
        echo "ctrl_panel is not running"
        exit 0
    fi
fi

if ! pid_matches_app "$pid"; then
    echo "PID $pid is not ctrl_panel app.py process, refuse to stop"
    ps -p "$pid" -o pid=,cmd= || true
    exit 1
fi

kill "$pid"

# 等待优雅退出
for _ in {1..30}; do
    if ! is_running "$pid"; then
        rm -f "$PID_FILE"
        echo "ctrl_panel stopped"
        exit 0
    fi
    sleep 0.2
done

echo "graceful stop timeout, force killing PID $pid"
kill -9 "$pid" 2>/dev/null || true
rm -f "$PID_FILE"
echo "ctrl_panel stopped (forced)"
