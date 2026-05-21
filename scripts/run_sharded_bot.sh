#!/usr/bin/env bash
# Pallas-Bot 分片一键启停：1 个控制台 (hub) + 多个牛牛进程 (worker)
#
#   ./scripts/run_sharded_bot.sh start
#   ./scripts/run_sharded_bot.sh status
#   ./scripts/run_sharded_bot.sh stop
#   ./scripts/run_sharded_bot.sh restart

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

RUN_DIR="${REPO_ROOT}/data/pallas_shard/run"
LOG_DIR="${REPO_ROOT}/data/pallas_shard/logs"
PID_HUB="${RUN_DIR}/hub.pid"
ACCOUNTS_JSON="${REPO_ROOT}/data/pallas_protocol/accounts.json"
REGISTRY_JSON="${REPO_ROOT}/data/pallas_shard/registry.json"

BOTS_PER_SHARD="${PALLAS_SHARD_BOTS_PER:-5}"
HUB_PORT="${PALLAS_SHARD_HUB_PORT:-${PORT:-8088}}"
WORKER_BASE_PORT="${PALLAS_SHARD_WORKER_BASE_PORT:-8090}"
WORKER_COUNT_OVERRIDE=""
DRY_RUN=0
SKIP_PORT_SYNC=0
SKIP_OCCUPIED_PORTS=1
START_CMD=(uv run python)
SYNC_PORTS_SCRIPT="${SCRIPT_DIR}/sync_shard_protocol_ports.py"
ALLOC_PORTS_SCRIPT="${SCRIPT_DIR}/apply_shard_worker_ports.py"
STARTUP_PORTS_SCRIPT="${SCRIPT_DIR}/shard_startup_ports.py"
WAIT_PORTS_SCRIPT="${SCRIPT_DIR}/wait_shard_worker_ports.py"
PORT_RELEASE_TIMEOUT="${PALLAS_SHARD_PORT_RELEASE_TIMEOUT:-60}"

print_rule() {
  echo "────────────────────────────────────────────────────────"
}

print_title() {
  echo ""
  echo "  $*"
  print_rule
}

usage() {
  cat <<EOF

用法:  ./scripts/run_sharded_bot.sh <命令> [选项]

命令:
  start     启动控制台与全部牛牛 worker（后台运行）
  stop      停止全部分片进程
  status    查看各进程是否在运行、对应端口
  restart   先 stop 再 start

常用示例:
  ./scripts/run_sharded_bot.sh start
  ./scripts/run_sharded_bot.sh status
  ./scripts/run_sharded_bot.sh restart

选项:
  --workers N          指定 worker 数量（默认按已启用牛牛账号自动计算）
  --bots-per-shard N   每个 worker 承载的牛牛数量（默认 5）
  --hub-port PORT      控制台 HTTP 端口（默认读 .env 的 PORT，否则 8088）
  --worker-base PORT   第一个 worker 的 WS 端口（默认 8090，依次为 8091、8092…）
  --skip-port-sync     启动前不自动改写协议端里的反向 WS 地址
  --no-skip-occupied-ports
                       worker 严格使用 起点+N，不自动避开已占用端口
  --dry-run            只显示将要执行的命令，不真正启动
  -h, --help           显示本帮助

启动后可在浏览器打开（将 PORT 换成你的 hub 端口）:
  WebUI    http://127.0.0.1:PORT/pallas/
  协议端   http://127.0.0.1:PORT/protocol/console/

运行日志目录: data/pallas_shard/logs/  （WebUI 日志页可查看各 worker）

EOF
}

read_dotenv_port() {
  local key="$1" default="$2"
  if [[ -f "${REPO_ROOT}/.env" ]]; then
    local line val
    line="$(grep -m1 "^${key}=" "${REPO_ROOT}/.env" 2>/dev/null || true)"
    if [[ -n "${line}" ]]; then
      val="${line#*=}"
      val="${val%%#*}"
      val="$(echo "${val}" | tr -d ' "'"'")"
      if [[ -n "${val}" ]]; then
        echo "${val}"
        return
      fi
    fi
  fi
  echo "${default}"
}

calc_worker_count() {
  python3 - "${REPO_ROOT}" "${BOTS_PER_SHARD}" "${ACCOUNTS_JSON}" "${REGISTRY_JSON}" <<'PY'
import json
import math
import sys
from pathlib import Path

root = Path(sys.argv[1])
bots_per = max(1, int(sys.argv[2]))
accounts_path = Path(sys.argv[3])
registry_path = Path(sys.argv[4])
need = 1

if accounts_path.is_file():
    try:
        raw = json.loads(accounts_path.read_text(encoding="utf-8"))
        items = raw.values() if isinstance(raw, dict) else raw
        enabled = 0
        for v in items:
            if isinstance(v, dict) and v.get("enabled", True):
                enabled += 1
        if enabled > 0:
            need = max(need, math.ceil(enabled / bots_per))
    except (json.JSONDecodeError, OSError, TypeError):
        pass

if registry_path.is_file():
    try:
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
        assigns = reg.get("assignments") or {}
        if assigns:
            max_sid = max(int(x) for x in assigns.values())
            need = max(need, max_sid + 1, math.ceil(len(assigns) / bots_per))
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        pass

print(need)
PY
}

is_running() {
  local pidfile="$1"
  [[ -f "${pidfile}" ]] || return 1
  local pid
  pid="$(cat "${pidfile}" 2>/dev/null || true)"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

start_one() {
  local name="$1"
  local label="$2"
  shift 2
  local pidfile="${RUN_DIR}/${name}.pid"
  local logfile="${LOG_DIR}/${name}.log"
  local bootstrap="${LOG_DIR}/${name}.bootstrap.log"

  if is_running "${pidfile}"; then
    echo "  · ${label}：已在运行（无需重复启动）"
    return 0
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "  · ${label}：将执行启动（预览）"
    return 0
  fi

  mkdir -p "${RUN_DIR}" "${LOG_DIR}"
  # 主日志由进程内 loguru 写入 ${logfile}（轮转）；bootstrap 仅捕获 init 前/崩溃输出
  nohup "$@" >>"${bootstrap}" 2>&1 &
  local pid=$!
  echo "${pid}" >"${pidfile}"
  echo "  · ${label}：已启动（日志 ${logfile}，启动期 ${bootstrap}）"
}

stop_one() {
  local name="$1"
  local label="$2"
  local pidfile="${RUN_DIR}/${name}.pid"
  if ! is_running "${pidfile}"; then
    rm -f "${pidfile}"
    echo "  · ${label}：未在运行"
    return 0
  fi
  local pid
  pid="$(cat "${pidfile}")"
  kill -TERM "${pid}" 2>/dev/null || true
  local i=0
  while kill -0 "${pid}" 2>/dev/null && [[ "${i}" -lt 30 ]]; do
    sleep 0.5
    i=$((i + 1))
  done
  if kill -0 "${pid}" 2>/dev/null; then
    kill -KILL "${pid}" 2>/dev/null || true
  fi
  rm -f "${pidfile}"
  echo "  · ${label}：已停止"
}

# 清理无 pid 文件的孤儿进程（重复 start 或手工杀父进程后残留）
stop_orphan_shard_processes() {
  local pat
  for pat in "${REPO_ROOT}/.venv/bin/python3 bot_hub.py" "${REPO_ROOT}/.venv/bin/python3 bot_worker.py"; do
    pkill -TERM -f "${pat}" 2>/dev/null || true
  done
  sleep 1
  for pat in "${REPO_ROOT}/.venv/bin/python3 bot_hub.py" "${REPO_ROOT}/.venv/bin/python3 bot_worker.py"; do
    pkill -KILL -f "${pat}" 2>/dev/null || true
  done
}

wait_worker_ports_released() {
  local workers="$1"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "  · worker 端口：将等待释放后再启动（预览）"
    return 0
  fi
  if [[ ! -f "${WAIT_PORTS_SCRIPT}" ]]; then
    echo "  · 未找到 wait_shard_worker_ports.py，等待 2s 后继续" >&2
    sleep 2
    return 0
  fi
  echo "  等待 worker 端口释放（登记见 registry.json，超时 ${PORT_RELEASE_TIMEOUT}s）…"
  if uv run python "${WAIT_PORTS_SCRIPT}" \
    --workers "${workers}" \
    --registry "${REGISTRY_JSON}" \
    --timeout "${PORT_RELEASE_TIMEOUT}" 2>&1 | sed 's/^/    /'; then
    return 0
  fi
  echo "  · 部分端口仍未释放，继续启动可能失败；可加大 PALLAS_SHARD_PORT_RELEASE_TIMEOUT 或检查占用" >&2
  return 1
}

registry_port_for_shard() {
  local sid="$1"
  python3 - "${REGISTRY_JSON}" "${sid}" "${WORKER_BASE_PORT}" <<'PY' 2>/dev/null || echo "$((WORKER_BASE_PORT + sid))"
import json
import sys
from pathlib import Path

path, sid, base = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
if not path.is_file():
    print(base + sid)
    raise SystemExit
raw = json.loads(path.read_text(encoding="utf-8"))
for row in raw.get("shards") or []:
    if int(row.get("id", -1)) == sid:
        print(int(row.get("port", base + sid)))
        raise SystemExit
print(base + sid)
PY
}

prepare_shard_ports() {
  local workers="$1"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "  · worker/协议端端口：将评估并按需更新（预览）"
    return 0
  fi
  if [[ ! -f "${STARTUP_PORTS_SCRIPT}" ]]; then
    echo "  · 未找到 shard_startup_ports.py，回退为仅分配 worker 端口" >&2
    allocate_worker_ports "${workers}" || return 1
    sync_shard_protocol_ports_legacy || true
    return 0
  fi
  mkdir -p "${RUN_DIR}"
  local backup="${RUN_DIR}/accounts.json.pre_sync"
  local prep_args=(
    --workers "${workers}"
    --base "${WORKER_BASE_PORT}"
    --env "${REPO_ROOT}/.env"
    --accounts "${ACCOUNTS_JSON}"
    --backup "${backup}"
  )
  if [[ "${SKIP_OCCUPIED_PORTS}" -eq 0 ]]; then
    prep_args+=(--no-skip-occupied)
  fi
  if [[ "${SKIP_PORT_SYNC}" -eq 1 ]]; then
    prep_args+=(--skip-protocol-sync)
  fi
  local out rc=0
  out="$(uv run python "${STARTUP_PORTS_SCRIPT}" "${prep_args[@]}" 2>&1)" || rc=$?
  if [[ "${rc}" -ne 0 ]]; then
    echo "  · 分片端口准备失败" >&2
    [[ -n "${out}" ]] && echo "${out}" | sed 's/^/    /' >&2
    return "${rc}"
  fi
  local ports_line
  ports_line="$(echo "${out}" | grep -E '^[0-9]+(,[0-9]+)*$' | tail -1)"
  if [[ -z "${ports_line}" ]]; then
    echo "  · 分片端口准备失败：无有效端口列表" >&2
    return 1
  fi
  WORKER_PORTS_CSV="${ports_line}"
  export WORKER_PORTS_CSV
  echo "${out}" | grep -v -E '^[0-9]+(,[0-9]+)*$' | grep -v -E '^skip_' | sed 's/^/    /' || true
}

allocate_worker_ports() {
  local workers="$1"
  local alloc_args=(--workers "${workers}" --base "${WORKER_BASE_PORT}" --env "${REPO_ROOT}/.env")
  if [[ "${SKIP_OCCUPIED_PORTS}" -eq 0 ]]; then
    alloc_args+=(--no-skip-occupied)
  fi
  local out rc=0
  out="$(uv run python "${ALLOC_PORTS_SCRIPT}" "${alloc_args[@]}" 2>&1)" || rc=$?
  if [[ "${rc}" -ne 0 ]]; then
    return "${rc}"
  fi
  WORKER_PORTS_CSV="$(echo "${out}" | grep -E '^[0-9]+(,[0-9]+)*$' | tail -1)"
  export WORKER_PORTS_CSV
}

sync_shard_protocol_ports_legacy() {
  if [[ "${SKIP_PORT_SYNC}" -eq 1 || ! -f "${ACCOUNTS_JSON}" ]]; then
    return 0
  fi
  uv run python "${SYNC_PORTS_SCRIPT}" \
    --accounts "${ACCOUNTS_JSON}" \
    --env "${REPO_ROOT}/.env" \
    --backup "${RUN_DIR}/accounts.json.pre_sync" >/dev/null 2>&1 || true
}

cmd_start() {
  local workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"
  local hub_url="http://127.0.0.1:${HUB_PORT}"

  print_title "Pallas-Bot 分片模式 · 启动"
  echo "  配置：控制台端口 ${HUB_PORT}，worker ${workers} 个，每片约 ${BOTS_PER_SHARD} 头牛"
  echo "        worker 起点端口 ${WORKER_BASE_PORT}$(
    [[ "${SKIP_OCCUPIED_PORTS}" -eq 1 ]] && echo "（自动跳过占用）" || echo "（严格 起点+分片号）"
  )"
  echo ""

  wait_worker_ports_released "${workers}" || true
  echo ""
  prepare_shard_ports "${workers}" || return 1
  if [[ -n "${WORKER_PORTS_CSV:-}" ]]; then
    echo "        实际端口：${WORKER_PORTS_CSV}"
  fi
  echo ""
  echo "  正在启动进程…"

  local common=(
    PALLAS_SHARD_ENABLED=true
    PALLAS_SHARD_BOTS_PER="${BOTS_PER_SHARD}"
    PALLAS_SHARD_HUB_PORT="${HUB_PORT}"
    PALLAS_SHARD_WORKER_BASE_PORT="${WORKER_BASE_PORT}"
  )

  start_one hub "控制台 (hub)" env \
    "${common[@]}" \
    PALLAS_BOT_ROLE=hub \
    PORT="${HUB_PORT}" \
    "${START_CMD[@]}" bot_hub.py

  if [[ "${DRY_RUN}" -eq 0 ]]; then
    sleep 1
  fi

  local sid=0
  IFS=',' read -r -a _worker_ports <<< "${WORKER_PORTS_CSV:-}"
  while [[ "${sid}" -lt "${workers}" ]]; do
    local wport=$((WORKER_BASE_PORT + sid))
    if [[ "${#_worker_ports[@]}" -gt "${sid}" && -n "${_worker_ports[sid]}" ]]; then
      wport="${_worker_ports[sid]}"
    fi
    start_one "worker-${sid}" "牛牛 worker-${sid}（WS 端口 ${wport}）" env \
      "${common[@]}" \
      PALLAS_BOT_ROLE=worker \
      PALLAS_SHARD_ID="${sid}" \
      PORT="${wport}" \
      "${START_CMD[@]}" bot_worker.py
    sid=$((sid + 1))
  done

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo ""
    echo "  （预览模式，未实际启动进程）"
    return 0
  fi

  echo ""
  echo "  正在确认进程是否就绪…"
  local hub_ok=0 worker_running=0 worker_fail=0
  if is_running "${PID_HUB}"; then
    hub_ok=1
  else
    echo "  · 控制台 hub 未在运行，请查看日志: ${LOG_DIR}/hub.log"
  fi
  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    if is_running "${f}"; then
      worker_running=$((worker_running + 1))
    else
      worker_fail=$((worker_fail + 1))
      local wname
      wname="$(basename "${f}" .pid)"
      echo "  · ${wname} 启动后已退出，请查看: ${LOG_DIR}/${wname}.log"
    fi
  done

  print_title "启动完成"
  if [[ "${hub_ok}" -eq 1 ]]; then
    echo "  在浏览器打开："
    echo "    WebUI   ${hub_url}/pallas/"
    echo "    协议端  ${hub_url}/protocol/console/"
  fi
  echo ""
  echo "  常用命令："
  echo "    ./scripts/run_sharded_bot.sh status   查看运行状态"
  echo "    ./scripts/run_sharded_bot.sh stop     停止全部分片"
  echo "    tail -f ${LOG_DIR}/worker-0.log       查看某 worker 日志"
  if [[ "${worker_fail}" -gt 0 ]]; then
    echo ""
    echo "  部分 worker 未保持运行，多为端口占用或配置错误；修复后执行 restart。"
  elif [[ "${hub_ok}" -eq 1 ]] && [[ "${worker_running}" -eq "${workers}" ]]; then
    echo ""
    echo "  全部进程已就绪。"
  fi
}

cmd_stop() {
  print_title "Pallas-Bot 分片模式 · 停止"
  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    local sid=""
    if [[ "$(basename "${f}" .pid)" =~ worker-([0-9]+) ]]; then
      sid="${BASH_REMATCH[1]}"
    fi
    stop_one "$(basename "${f}" .pid)" "牛牛 worker-${sid}"
  done
  stop_one hub "控制台 (hub)"
  stop_orphan_shard_processes
  echo ""
  echo "  全部分片进程已处理完毕。"
}

cmd_status() {
  local workers=0
  local running_workers=0
  local stale_workers=0
  local hub_url="http://127.0.0.1:${HUB_PORT}"

  print_title "Pallas-Bot 分片模式 · 运行状态"

  if is_running "${PID_HUB}"; then
    echo "  控制台 (hub)     运行中"
    echo "                   ${hub_url}/pallas/"
    echo "                   ${hub_url}/protocol/console/"
  else
    if [[ -f "${PID_HUB}" ]]; then
      echo "  控制台 (hub)     未运行（残留 pid 文件，可执行 start 清理并拉起）"
    else
      echo "  控制台 (hub)     未运行"
    fi
  fi

  echo ""
  echo "  牛牛 worker："
  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    workers=$((workers + 1))
    local name pid port
    name="$(basename "${f}" .pid)"
    port=""
    if [[ "${name}" =~ worker-([0-9]+) ]]; then
      port="$(registry_port_for_shard "${BASH_REMATCH[1]}")"
    fi
    if is_running "${f}"; then
      running_workers=$((running_workers + 1))
      echo "    ${name}   运行中   反向 WS 端口 ${port}"
    else
      stale_workers=$((stale_workers + 1))
      echo "    ${name}   未运行   （进程已退出，日志 ${LOG_DIR}/${name}.log）"
    fi
  done
  if [[ "${workers}" -eq 0 ]]; then
    echo "    （尚无 worker 记录，请先 start）"
  fi

  echo ""
  echo "  日志目录：${LOG_DIR}/"
  echo "  （WebUI「日志」页可汇总查看 hub + 各 worker）"

  if [[ "${stale_workers}" -gt 0 ]]; then
    echo ""
    echo "  提示：有 ${stale_workers} 个 worker 未在运行，可执行："
    echo "    ./scripts/run_sharded_bot.sh restart"
  elif [[ "${running_workers}" -eq 0 ]] && ! is_running "${PID_HUB}"; then
    echo ""
    echo "  当前无运行中的分片进程。启动请执行："
    echo "    ./scripts/run_sharded_bot.sh start"
  fi
}

cmd_restart() {
  local workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"
  cmd_stop
  echo ""
  wait_worker_ports_released "${workers}" || true
  echo ""
  cmd_start
}

# --- parse ---
ACTION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    start|stop|status|restart)
      ACTION="$1"
      shift
      ;;
    --workdir)
      REPO_ROOT="$(cd "$2" && pwd)"
      cd "${REPO_ROOT}"
      RUN_DIR="${REPO_ROOT}/data/pallas_shard/run"
      LOG_DIR="${REPO_ROOT}/data/pallas_shard/logs"
      PID_HUB="${RUN_DIR}/hub.pid"
      ACCOUNTS_JSON="${REPO_ROOT}/data/pallas_protocol/accounts.json"
      REGISTRY_JSON="${REPO_ROOT}/data/pallas_shard/registry.json"
      shift 2
      ;;
    --workers)
      WORKER_COUNT_OVERRIDE="$2"
      shift 2
      ;;
    --bots-per-shard)
      BOTS_PER_SHARD="$2"
      shift 2
      ;;
    --hub-port)
      HUB_PORT="$2"
      shift 2
      ;;
    --worker-base)
      WORKER_BASE_PORT="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-port-sync)
      SKIP_PORT_SYNC=1
      shift
      ;;
    --no-skip-occupied-ports)
      SKIP_OCCUPIED_PORTS=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1（使用 -h 查看帮助）" >&2
      usage >&2
      exit 1
      ;;
  esac
done

HUB_PORT="${PALLAS_SHARD_HUB_PORT:-$(read_dotenv_port PORT "${HUB_PORT}")}"
WORKER_BASE_PORT="${PALLAS_SHARD_WORKER_BASE_PORT:-$(read_dotenv_port PALLAS_SHARD_WORKER_BASE_PORT "${WORKER_BASE_PORT}")}"

if [[ -z "${ACTION}" ]]; then
  usage >&2
  exit 1
fi

case "${ACTION}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  restart) cmd_restart ;;
esac
