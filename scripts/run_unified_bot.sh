#!/usr/bin/env bash
# 单进程 unified 启停
#
#   ./scripts/run_unified_bot.sh start
#   ./scripts/run_unified_bot.sh status
#   ./scripts/run_unified_bot.sh stop
#   ./scripts/run_unified_bot.sh restart

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

RUN_DIR="${REPO_ROOT}/data/pallas_unified/run"
LOG_DIR="${REPO_ROOT}/data/pallas_unified/logs"
ACCOUNTS_JSON="${REPO_ROOT}/data/pallas_protocol/accounts.json"
PID_FILE="${RUN_DIR}/bot.pid"
LOG_FILE="${LOG_DIR}/bot.log"
START_CMD=(uv run python bot.py)
SYNC_PORTS_SCRIPT="${SCRIPT_DIR}/sync_unified_protocol_ports.py"
SKIP_PORT_SYNC=0

read_listen_port() {
  if [[ -n "${PORT:-}" ]]; then
    echo "${PORT}"
    return
  fi
  uv run python - <<'PY'
from src.platform.shard.registry.sync_unified_protocol_ports import resolve_unified_listen_port
from pathlib import Path
print(resolve_unified_listen_port(env_path=Path(".env")))
PY
}

is_running() {
  [[ -f "${PID_FILE}" ]] || return 1
  local pid
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  [[ -n "${pid}" ]] || return 1
  kill -0 "${pid}" 2>/dev/null
}

prepare_unified_ports() {
  local port="$1"
  if [[ "${SKIP_PORT_SYNC}" -eq 1 || ! -f "${SYNC_PORTS_SCRIPT}" || ! -f "${ACCOUNTS_JSON}" ]]; then
    return 0
  fi
  local backup="${RUN_DIR}/accounts.json.pre_sync"
  mkdir -p "${RUN_DIR}"
  local out rc=0
  out="$(uv run python "${SYNC_PORTS_SCRIPT}" --port "${port}" --backup "${backup}" 2>&1)" || rc=$?
  if [[ "${rc}" -ne 0 ]]; then
    echo "unified 协议端端口同步失败" >&2
    [[ -n "${out}" ]] && echo "${out}" | sed 's/^/  /' >&2
    return "${rc}"
  fi
  if [[ -n "${out}" ]]; then
    echo "${out}" | sed 's/^/  /'
  fi
  return 0
}

start_bot() {
  mkdir -p "${RUN_DIR}" "${LOG_DIR}"
  if is_running; then
    echo "unified 已在运行 (pid $(cat "${PID_FILE}"))"
    return 0
  fi
  local port
  port="$(read_listen_port)"
  prepare_unified_ports "${port}" || return 1
  export PALLAS_SHARD_ENABLED=false
  export PALLAS_BOT_ROLE=unified
  export PORT="${port}"
  nohup env PALLAS_SHARD_ENABLED=false PALLAS_BOT_ROLE=unified PORT="${port}" \
    "${START_CMD[@]}" >>"${LOG_FILE}" 2>&1 &
  echo $! >"${PID_FILE}"
  sleep 2
  if is_running; then
    echo "unified 已启动 pid=$(cat "${PID_FILE}") port=${port}"
    echo "WebUI: http://127.0.0.1:${port}/pallas/"
    echo "日志: ${LOG_FILE}"
  else
    echo "unified 启动失败，查看 ${LOG_FILE}" >&2
    return 1
  fi
}

stop_bot() {
  if ! is_running; then
    rm -f "${PID_FILE}"
    echo "unified 未运行"
    return 0
  fi
  local pid
  pid="$(cat "${PID_FILE}")"
  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 30); do
    kill -0 "${pid}" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "${pid}" 2>/dev/null; then
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -f "${PID_FILE}"
  echo "unified 已停止"
}

status_bot() {
  local port
  port="$(read_listen_port)"
  echo "PALLAS_SHARD_ENABLED=false (期望)"
  echo "监听端口 ${port}"
  if is_running; then
    echo "状态 运行中 pid=$(cat "${PID_FILE}")"
    echo "WebUI http://127.0.0.1:${port}/pallas/"
  else
    echo "状态 未运行"
  fi
  echo "日志 ${LOG_FILE}"
}

observability_bot() {
  if ! is_running; then
    echo "unified 未运行，无法读取 dispatch 指标" >&2
    return 1
  fi
  uv run python "${SCRIPT_DIR}/ingress_dispatch_status.py"
}

usage() {
  cat <<EOF
用法: $0 {start|stop|restart|status|observability} [选项]

选项:
  --skip-port-sync   启动前不同步协议端 ws_url
  -h, --help         显示本帮助
EOF
}

cmd=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    start|stop|restart|status|observability) cmd="$1"; shift ;;
    --skip-port-sync) SKIP_PORT_SYNC=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "未知参数: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

cmd="${cmd:-status}"
case "${cmd}" in
  start) start_bot ;;
  stop) stop_bot ;;
  restart) stop_bot; start_bot ;;
  status) status_bot ;;
  observability) observability_bot ;;
  *)
    echo "用法: $0 {start|stop|restart|status|observability}" >&2
    exit 1
    ;;
esac
