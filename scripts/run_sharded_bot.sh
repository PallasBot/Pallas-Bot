#!/usr/bin/env bash
# Pallas-Bot 分片一键启停：1 个控制台 (hub) + 多个牛牛进程 (worker)
#
#   ./scripts/run_sharded_bot.sh start
#   ./scripts/run_sharded_bot.sh status
#   ./scripts/run_sharded_bot.sh stop
#   ./scripts/run_sharded_bot.sh restart
#   ./scripts/run_sharded_bot.sh restart --workers-only
#   ./scripts/run_sharded_bot.sh start --hub-only
#   ./scripts/run_sharded_bot.sh stop --hub-only

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
WORKERS_ONLY=0
HUB_ONLY=0
SCALE_ONLY=0
DRY_RUN=0
SKIP_PORT_SYNC=0
SKIP_OCCUPIED_PORTS=1
START_CMD=(uv run python)
SYNC_PORTS_SCRIPT="${SCRIPT_DIR}/sync_shard_protocol_ports.py"
ALLOC_PORTS_SCRIPT="${SCRIPT_DIR}/apply_shard_worker_ports.py"
STARTUP_PORTS_SCRIPT="${SCRIPT_DIR}/shard_startup_ports.py"
WAIT_PORTS_SCRIPT="${SCRIPT_DIR}/wait_shard_worker_ports.py"
SHARD_TEST_SCRIPT="${SCRIPT_DIR}/shard_test_worker.py"
DETECT_REDIS_SCRIPT="${SCRIPT_DIR}/detect_shard_redis.py"
PORT_RELEASE_TIMEOUT="${PALLAS_SHARD_PORT_RELEASE_TIMEOUT:-60}"
FORCE_STOP=0
PID_WORKER_TEST="${RUN_DIR}/worker-test.pid"
TEST_SHARD_ID="${PALLAS_SHARD_TEST_ID:-99}"

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
  start     启动控制台与全部牛牛 worker（可加 --hub-only 仅启 hub；--workers-only 仅拉起缺失 worker）
  stop      停止全部分片进程（可加 --workers-only 仅停 worker，或 --hub-only 仅停 hub）
  status    查看进程、端口、Redis 协调与配置摘要
  restart   先 stop 再 start（可加 --workers-only 仅重启 worker，或 --hub-only 仅重启 hub）

测试 worker（手动迁入账号，不参与自动负载）:
  test init              在 registry 中启用 test 分片并分配端口
  test add <QQ>          将 QQ 迁入测试分片（可加 --sync-ws）
  test remove <QQ>       从测试分片移除
  test list              列出测试分片账号
  test sync-ws           同步测试账号协议端 ws_url
  test start|stop|status|restart   仅启停测试 worker 进程（worker-test）

常用示例:
  ./scripts/run_sharded_bot.sh start
  ./scripts/run_sharded_bot.sh status
  ./scripts/run_sharded_bot.sh restart
  ./scripts/run_sharded_bot.sh restart --workers-only
  ./scripts/run_sharded_bot.sh start --workers-only
  ./scripts/run_sharded_bot.sh start --hub-only
  ./scripts/run_sharded_bot.sh stop --hub-only
  ./scripts/run_sharded_bot.sh restart --hub-only
  ./scripts/run_sharded_bot.sh hub-start
  ./scripts/run_sharded_bot.sh test init
  ./scripts/run_sharded_bot.sh test add 123456789 --sync-ws
  ./scripts/run_sharded_bot.sh test start

选项:
  --workers N          指定 worker 数量（默认按已启用牛牛账号自动计算）
  --bots-per-shard N   每个 worker 承载的牛牛数量（默认 5）
  --hub-port PORT      控制台 HTTP 端口（默认读 .env 的 PORT，否则 8088）
  --worker-base PORT   第一个 worker 的 WS 端口（默认 8090，依次为 8091、8092…）
  --skip-port-sync     启动前不自动改写协议端里的反向 WS 地址
  --no-skip-occupied-ports
                       worker 严格使用 起点+N，不自动避开已占用端口
  --workers-only       仅操作生产 worker（不停/不启 hub；start 时只拉起缺失进程，restart 时全量重启）
  --scale-only         扩容模式：不重分配端口、不同步协议端 ws_url（已有 worker 在跑时 start --workers-only 自动启用）
  --hub-only           仅操作 hub 控制台（不停/不启 worker；restart 时常用）
  --force              stop/restart 时 SIGKILL 强杀并跳过端口长等待（加快重启）
  --dry-run            只显示将要执行的命令，不真正启动
  -h, --help           显示本帮助

启动后可在浏览器打开（将 PORT 换成你的 hub 端口）:
  WebUI    http://127.0.0.1:PORT/pallas/
  协议端   http://127.0.0.1:PORT/protocol/console/

运行日志目录: data/pallas_shard/logs/  （WebUI 日志页可查看各 worker）

EOF
}

load_shard_redis_env() {
  # 与 Pallas-Bot-AI 共用 REDIS_URL 时自动启用跨进程 claim。
  if [[ ! -f "${DETECT_REDIS_SCRIPT}" ]]; then
    return 0
  fi
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    export "${line?}"
  done < <("${START_CMD[@]}" "${DETECT_REDIS_SCRIPT}" 2>/dev/null || true)
}

shard_coord_backend_hint() {
  if [[ "${PALLAS_COORD_REDIS_ENABLED:-}" == "true" && -n "${PALLAS_COORD_REDIS_URL:-}" ]]; then
    echo "跨进程 claim：Redis"
  else
    echo "跨进程 claim：Redis 未就绪（分片 claim 不可用）"
  fi
}

REDIS_STATUS_LINES=()

load_redis_status_lines() {
  REDIS_STATUS_LINES=()
  if [[ ! -f "${DETECT_REDIS_SCRIPT}" ]]; then
    return
  fi
  mapfile -t REDIS_STATUS_LINES < <("${START_CMD[@]}" "${DETECT_REDIS_SCRIPT}" --status 2>/dev/null || true)
}

redis_status_get() {
  local key="$1" line
  for line in "${REDIS_STATUS_LINES[@]}"; do
    [[ "${line}" == "${key}="* ]] || continue
    echo "${line#*=}"
    return
  done
}

print_redis_status_block() {
  echo "  跨进程协调 (ingress claim)"
  if [[ ! -f "${DETECT_REDIS_SCRIPT}" ]]; then
    echo "    状态     未找到探测脚本，无法确认 Redis"
    return
  fi
  load_redis_status_lines
  local policy url pkg reachable active backend
  policy="$(redis_status_get policy)"
  url="$(redis_status_get url)"
  pkg="$(redis_status_get package)"
  reachable="$(redis_status_get reachable)"
  active="$(redis_status_get active)"
  backend="$(redis_status_get backend)"
  policy="${policy:-auto}"
  backend="${backend:-file}"
  if [[ "${policy}" == "false" ]]; then
    echo "    策略     已禁用 (PALLAS_COORD_REDIS_ENABLED=false)"
    echo "    状态     分片 claim 不可用"
    return
  fi
  if [[ -z "${url}" ]]; then
    echo "    策略     ${policy}"
    echo "    配置     未设置 REDIS_URL（pallas.toml [env] 或 webui.json）"
    echo "    状态     分片 claim 不可用"
    return
  fi
  echo "    策略     ${policy}"
  echo "    地址     ${url}"
  if [[ "${pkg}" == "no" ]]; then
    echo "    客户端   未安装（uv sync --extra coord-redis）"
  else
    echo "    客户端   已安装"
  fi
  if [[ "${reachable}" == "yes" ]]; then
    echo "    连通     可达 → 启动 worker 时将使用 Redis"
  else
    echo "    连通     不可达 → 分片 claim 不可用"
  fi
  if [[ "${active}" == "yes" ]]; then
    echo "    当前     Redis 已启用"
  else
    echo "    当前     Redis 未启用"
  fi
}

print_observability_status_block() {
  echo "  分片可观测"
  local status_script="${SCRIPT_DIR}/shard_observability_status.py"
  if [[ ! -f "${status_script}" ]]; then
    echo "    （未找到 shard_observability_status.py）"
    return
  fi
  local -a obs_env=()
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    obs_env+=("${line}")
  done < <(shard_common_env)
  local out=""
  if out="$(env "${obs_env[@]}" uv run python "${status_script}" 2>/dev/null)"; then
    while IFS= read -r line; do
      [[ -n "${line}" ]] || continue
      echo "    ${line}"
    done <<< "${out}"
  else
    echo "    （读取失败；请确认 data/pallas_shard/stats 可访问）"
  fi
}

shard_common_env() {
  (
    echo "PALLAS_SHARD_ENABLED=true"
    echo "PALLAS_BOT_ROLE=hub"
    echo "PALLAS_SHARD_BOTS_PER=${BOTS_PER_SHARD}"
    echo "PALLAS_SHARD_HUB_PORT=${HUB_PORT}"
    echo "PALLAS_SHARD_WORKER_BASE_PORT=${WORKER_BASE_PORT}"
  )
}

print_config_summary() {
  local workers="$1"
  echo "  每片牛数   ${BOTS_PER_SHARD}"
  echo "  worker 数  ${workers}"
  echo "  hub 端口   ${HUB_PORT}"
  echo "  worker 起点 ${WORKER_BASE_PORT}"
  if [[ -n "${WORKER_PORTS_CSV:-}" ]]; then
    echo "  worker 端口 ${WORKER_PORTS_CSV}"
  fi
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

CALC_WORKERS_SCRIPT="${SCRIPT_DIR}/calc_worker_count.py"

calc_worker_count() {
  local -a args=(--bots-per "${BOTS_PER_SHARD}" --accounts "${ACCOUNTS_JSON}" --registry "${REGISTRY_JSON}")
  if [[ -n "${WORKER_BASE_PORT:-}" ]]; then
    args+=(--base "${WORKER_BASE_PORT}")
  fi
  if [[ ! -f "${CALC_WORKERS_SCRIPT}" ]]; then
    echo 1
    return
  fi
  uv run python "${CALC_WORKERS_SCRIPT}" "${args[@]}" 2>/dev/null || echo 1
}

is_running() {
  local pidfile="$1"
  [[ -f "${pidfile}" ]] || return 1
  local pid
  pid="$(cat "${pidfile}" 2>/dev/null || true)"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

rotate_bootstrap_log() {
  local name="$1"
  local bootstrap="$2"
  [[ -f "${bootstrap}" ]] || return 0
  local size=0
  size="$(wc -c <"${bootstrap}" 2>/dev/null | tr -d ' ')" || size=0
  if [[ "${size}" -eq 0 ]]; then
    rm -f "${bootstrap}"
    return 0
  fi
  mkdir -p "${LOG_DIR}/archive"
  local ts
  ts="$(date +%Y%m%d-%H%M%S)"
  mv -f "${bootstrap}" "${LOG_DIR}/archive/${name}.bootstrap-${ts}.log"
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
  rotate_bootstrap_log "${name}" "${bootstrap}"
  # 主日志由进程内 loguru 写入 ${logfile}（每次启动归档旧会话）；bootstrap 仅捕获 init 前/崩溃输出
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
  if [[ "${FORCE_STOP}" -eq 1 ]]; then
    kill -KILL "${pid}" 2>/dev/null || true
    pkill -KILL -P "${pid}" 2>/dev/null || true
    rm -f "${pidfile}"
    echo "  · ${label}：已强制停止"
    return 0
  fi
  kill -TERM "${pid}" 2>/dev/null || true
  local i=0
  while kill -0 "${pid}" 2>/dev/null && [[ "${i}" -lt 30 ]]; do
    sleep 0.5
    i=$((i + 1))
  done
  if kill -0 "${pid}" 2>/dev/null; then
    kill -KILL "${pid}" 2>/dev/null || true
    pkill -KILL -P "${pid}" 2>/dev/null || true
  fi
  rm -f "${pidfile}"
  echo "  · ${label}：已停止"
}

# 清理无 pid 文件的孤儿进程（重复 start 或手工杀父进程后残留）
stop_orphan_shard_processes() {
  local pat
  for pat in "${REPO_ROOT}/.venv/bin/python3 bot_hub.py" "${REPO_ROOT}/.venv/bin/python3 bot_worker.py"; do
    if [[ "${FORCE_STOP}" -eq 1 ]]; then
      pkill -KILL -f "${pat}" 2>/dev/null || true
    else
      pkill -TERM -f "${pat}" 2>/dev/null || true
    fi
  done
  if [[ "${FORCE_STOP}" -eq 1 ]]; then
    return 0
  fi
  sleep 1
  for pat in "${REPO_ROOT}/.venv/bin/python3 bot_hub.py" "${REPO_ROOT}/.venv/bin/python3 bot_worker.py"; do
    pkill -KILL -f "${pat}" 2>/dev/null || true
  done
}

stop_orphan_worker_processes() {
  local pat="${REPO_ROOT}/.venv/bin/python3 bot_worker.py"
  if [[ "${FORCE_STOP}" -eq 1 ]]; then
    pkill -KILL -f "${pat}" 2>/dev/null || true
    return 0
  fi
  pkill -TERM -f "${pat}" 2>/dev/null || true
  sleep 1
  pkill -KILL -f "${pat}" 2>/dev/null || true
}

stop_orphan_hub_processes() {
  local pat="${REPO_ROOT}/.venv/bin/python3 bot_hub.py"
  if [[ "${FORCE_STOP}" -eq 1 ]]; then
    pkill -KILL -f "${pat}" 2>/dev/null || true
    return 0
  fi
  pkill -TERM -f "${pat}" 2>/dev/null || true
  sleep 1
  pkill -KILL -f "${pat}" 2>/dev/null || true
}

start_hub_process() {
  local -a common
  mapfile -t common < <(shard_common_env)
  start_one hub "hub  控制台 :${HUB_PORT}" env \
    "${common[@]}" \
    PALLAS_BOT_ROLE=hub \
    PORT="${HUB_PORT}" \
    "${START_CMD[@]}" bot_hub.py
}

stop_hub_process() {
  stop_one hub "hub  控制台"
  stop_orphan_hub_processes
}

count_running_production_workers() {
  local running=0 total=0 f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    [[ "$(basename "${f}" .pid)" == "worker-test" ]] && continue
    total=$((total + 1))
    if is_running "${f}"; then
      running=$((running + 1))
    fi
  done
  echo "${running} ${total}"
}

stop_production_workers() {
  local f sid
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    [[ "$(basename "${f}" .pid)" == "worker-test" ]] && continue
    sid=""
    if [[ "$(basename "${f}" .pid)" =~ worker-([0-9]+) ]]; then
      sid="${BASH_REMATCH[1]}"
    fi
    stop_one "$(basename "${f}" .pid)" "worker-${sid}"
  done
  stop_orphan_worker_processes
}

worker_port_for_sid() {
  local sid="$1"
  registry_port_for_shard "${sid}"
}

start_production_workers() {
  local workers="$1"
  local -a common
  mapfile -t common < <(shard_common_env)
  load_shard_redis_env
  local sid=0
  local -a _worker_ports=()
  if [[ -n "${WORKER_PORTS_CSV:-}" ]]; then
    IFS=',' read -r -a _worker_ports <<< "${WORKER_PORTS_CSV}"
  fi
  while [[ "${sid}" -lt "${workers}" ]]; do
    local wport
    wport="$(worker_port_for_sid "${sid}")"
    if [[ "${#_worker_ports[@]}" -gt "${sid}" && -n "${_worker_ports[sid]:-}" ]]; then
      wport="${_worker_ports[sid]}"
    fi
    start_one "worker-${sid}" "worker-${sid}  WS:${wport}" env \
      "${common[@]}" \
      PALLAS_BOT_ROLE=worker \
      PALLAS_SHARD_ID="${sid}" \
      PORT="${wport}" \
      "${START_CMD[@]}" bot_worker.py
    sid=$((sid + 1))
  done
}

start_missing_production_workers() {
  local workers="$1"
  local -a common
  mapfile -t common < <(shard_common_env)
  load_shard_redis_env
  local sid=0
  while [[ "${sid}" -lt "${workers}" ]]; do
    local wport pidfile
    pidfile="${RUN_DIR}/worker-${sid}.pid"
    wport="$(worker_port_for_sid "${sid}")"
    if is_running "${pidfile}"; then
      echo "  · worker-${sid}  WS:${wport}：已在运行（无需重复启动）"
      sid=$((sid + 1))
      continue
    fi
    start_one "worker-${sid}" "worker-${sid}  WS:${wport}" env \
      "${common[@]}" \
      PALLAS_BOT_ROLE=worker \
      PALLAS_SHARD_ID="${sid}" \
      PORT="${wport}" \
      "${START_CMD[@]}" bot_worker.py
    sid=$((sid + 1))
  done
}

count_running_production_worker_ids() {
  local running=0
  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    [[ "$(basename "${f}" .pid)" == "worker-test" ]] && continue
    if is_running "${f}"; then
      running=$((running + 1))
    fi
  done
  echo "${running}"
}

wait_worker_ports_released() {
  local workers="$1"
  if [[ "${FORCE_STOP}" -eq 1 ]]; then
    echo "  · worker 端口：强制模式，短等待 3s"
    sleep 3
    return 0
  fi
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

registry_test_enabled() {
  python3 - "${REGISTRY_JSON}" <<'PY' 2>/dev/null
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.is_file():
    raise SystemExit(1)
raw = json.loads(p.read_text(encoding="utf-8"))
test = raw.get("test") or {}
raise SystemExit(0 if test.get("enabled") else 1)
PY
}

registry_test_port() {
  python3 - "${REGISTRY_JSON}" "${TEST_SHARD_ID}" "${WORKER_BASE_PORT}" <<'PY'
import json, sys
from pathlib import Path
path, test_sid, base = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
if not path.is_file():
    print(base + 100)
    raise SystemExit
raw = json.loads(path.read_text(encoding="utf-8"))
test = raw.get("test") or {}
sid = int(test.get("shard_id", test_sid))
port = int(test.get("port", 0))
if port > 0:
    print(port)
    raise SystemExit
for row in raw.get("shards") or []:
    if int(row.get("id", -1)) == sid:
        print(int(row.get("port", base + sid)))
        raise SystemExit
normal = [int(r.get("port", 0)) for r in (raw.get("shards") or []) if int(r.get("id", -1)) != sid]
print(max(normal or [base - 1]) + 1)
PY
}

registry_test_shard_id() {
  python3 - "${REGISTRY_JSON}" "${TEST_SHARD_ID}" <<'PY' 2>/dev/null
import json, sys
from pathlib import Path
raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
test = raw.get("test") or {}
print(int(test.get("shard_id", int(sys.argv[2]))))
PY
}

run_shard_test_cli() {
  uv run python "${SHARD_TEST_SCRIPT}" --env "${REPO_ROOT}/.env" --accounts "${ACCOUNTS_JSON}" "$@"
}

cmd_test_start() {
  if ! registry_test_enabled; then
    echo "  测试分片未启用。请先执行: ./scripts/run_sharded_bot.sh test init" >&2
    return 1
  fi
  local tsid tport
  tsid="$(registry_test_shard_id)"
  tport="$(registry_test_port)"
  print_title "Pallas-Bot 测试 worker · 启动"
  echo "  测试分片 id=${tsid}，WS 端口 ${tport}"
  load_shard_redis_env
  echo "  $(shard_coord_backend_hint)"
  echo ""
  local common=(
    PALLAS_SHARD_ENABLED=true
    PALLAS_SHARD_BOTS_PER="${BOTS_PER_SHARD}"
    PALLAS_SHARD_HUB_PORT="${HUB_PORT}"
    PALLAS_SHARD_WORKER_BASE_PORT="${WORKER_BASE_PORT}"
  )
  start_one "worker-test" "测试 worker-test（WS 端口 ${tport}）" env \
    "${common[@]}" \
    PALLAS_BOT_ROLE=worker \
    PALLAS_SHARD_ID="${tsid}" \
    PORT="${tport}" \
    "${START_CMD[@]}" bot_worker.py
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  if is_running "${PID_WORKER_TEST}"; then
    echo ""
    echo "  测试 worker 已就绪。日志: ${LOG_DIR}/worker-test.log"
  else
    echo ""
    echo "  测试 worker 启动后已退出，请查看: ${LOG_DIR}/worker-test.log"
    return 1
  fi
}

cmd_test_stop() {
  print_title "Pallas-Bot 测试 worker · 停止"
  stop_one "worker-test" "测试 worker-test"
}

cmd_test_status() {
  print_title "Pallas-Bot 测试 worker · 状态"
  if ! registry_test_enabled; then
    echo "  registry.test：未启用（test init 后可用）"
    return 0
  fi
  local tsid tport
  tsid="$(registry_test_shard_id)"
  tport="$(registry_test_port)"
  echo "  分片 id=${tsid}，WS 端口 ${tport}"
  run_shard_test_cli list 2>/dev/null | sed 's/^/    /' || true
  echo ""
  if is_running "${PID_WORKER_TEST}"; then
    echo "  进程：运行中（worker-test）"
    echo "  日志：${LOG_DIR}/worker-test.log"
  else
    echo "  进程：未运行"
    echo "  启动：./scripts/run_sharded_bot.sh test start"
  fi
}

cmd_test_restart() {
  cmd_test_stop
  echo ""
  cmd_test_start
}

dispatch_test_subcmd() {
  local sub="${1:-}"
  shift || true
  case "${sub}" in
    init)
      print_title "注册表 · 启用 test 分片"
      run_shard_test_cli init "$@"
      ;;
    add)
      if [[ $# -lt 1 ]]; then
        echo "用法: test add <QQ> [--sync-ws]" >&2
        return 1
      fi
      local qq="$1" sync_flag=()
      shift
      if [[ "${1:-}" == "--sync-ws" ]]; then
        sync_flag=(--sync-ws)
        shift
      fi
      print_title "注册表 · 迁入测试分片 ${qq}"
      run_shard_test_cli add "${qq}" "${sync_flag[@]}"
      ;;
    remove)
      if [[ $# -lt 1 ]]; then
        echo "用法: test remove <QQ>" >&2
        return 1
      fi
      print_title "注册表 · 移出测试分片 $1"
      run_shard_test_cli remove "$1"
      ;;
    list)
      run_shard_test_cli list
      ;;
    sync|sync-ws)
      print_title "协议端 · 同步测试分片 ws_url"
      run_shard_test_cli sync-ws "$@"
      ;;
    start) cmd_test_start ;;
    stop) cmd_test_stop ;;
    status) cmd_test_status ;;
    restart) cmd_test_restart ;;
    "")
      echo "用法: test <init|add|remove|list|sync-ws|start|stop|status|restart> ..." >&2
      return 1
      ;;
    *)
      echo "未知 test 子命令: ${sub}" >&2
      return 1
      ;;
  esac
}

cmd_start_hub_only() {
  local hub_url="http://127.0.0.1:${HUB_PORT}"
  local worker_counts
  worker_counts="$(count_running_production_workers)"
  local worker_running="${worker_counts%% *}"
  local worker_total="${worker_counts##* }"

  print_title "Pallas-Bot 分片模式 · 启动 hub（不启 worker）"
  echo "  hub 端口   ${HUB_PORT}"
  if [[ "${worker_total}" -gt 0 ]]; then
    echo "  worker     保持现状（${worker_running}/${worker_total} 运行，本次不启动 worker）"
  else
    echo "  worker     本次不启动（需单独 start 或 restart --workers-only）"
  fi
  load_shard_redis_env
  echo "  $(shard_coord_backend_hint)"
  echo ""
  echo "  正在启动 hub…"

  start_hub_process

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo ""
    echo "  （预览模式，未实际启动进程）"
    return 0
  fi

  echo ""
  echo "  正在确认 hub 是否就绪…"
  local hub_ok=0
  if is_running "${PID_HUB}"; then
    hub_ok=1
  else
    echo "  · 控制台 hub 未在运行，请查看日志: ${LOG_DIR}/hub.log"
  fi

  print_title "hub 启动完成"
  echo "  汇总       hub $([[ "${hub_ok}" -eq 1 ]] && echo 运行中 || echo 未就绪)"
  if [[ "${hub_ok}" -eq 1 ]]; then
    echo "  WebUI      ${hub_url}/pallas/"
    echo "  协议端     ${hub_url}/protocol/console/"
  fi
  echo ""
  echo "  常用命令"
  echo "    status                  查看运行状态"
  echo "    start --workers-only    仅拉起缺失 worker"
  echo "    restart --workers-only  全量重启 worker"
  echo "    restart --hub-only       仅重启 hub"
  if [[ "${hub_ok}" -eq 0 ]]; then
    return 1
  fi
}

cmd_start_workers_only() {
  local workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"
  local running_before
  running_before="$(count_running_production_worker_ids)"
  if [[ "${SCALE_ONLY}" -eq 0 && "${running_before}" -gt 0 ]]; then
    SCALE_ONLY=1
  fi

  print_title "Pallas-Bot 分片模式 · 启动缺失 worker（保留已运行进程）"
  print_config_summary "${workers}"
  if is_running "${PID_HUB}"; then
    echo "  hub        保持运行（:${HUB_PORT}）"
  else
    echo "  hub        未运行（本次不启动 hub）"
  fi
  if [[ "${SCALE_ONLY}" -eq 1 ]]; then
    echo "  端口策略   扩容模式（registry 端口，不重分配、不同步协议端）"
  else
    echo "  端口策略   冷启动（评估端口并同步协议端 ws_url）"
  fi
  load_shard_redis_env
  echo "  $(shard_coord_backend_hint)"
  echo ""

  if [[ "${SCALE_ONLY}" -eq 1 ]]; then
    workers="$(calc_worker_count)"
    echo "  正在启动缺失 worker（已在运行的分片将跳过）…"
    start_missing_production_workers "${workers}"
  else
    prepare_shard_ports "${workers}" || return 1
    workers="$(calc_worker_count)"
    echo ""
    echo "  正在启动 worker…"
    start_production_workers "${workers}"
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo ""
    echo "  （预览模式，未实际启动）"
    return 0
  fi

  echo ""
  echo "  正在确认 worker…"
  local worker_running=0 worker_fail=0
  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    [[ "$(basename "${f}" .pid)" == "worker-test" ]] && continue
    if is_running "${f}"; then
      worker_running=$((worker_running + 1))
    else
      worker_fail=$((worker_fail + 1))
      local wname
      wname="$(basename "${f}" .pid)"
      echo "  · ${wname} 启动后已退出，请查看: ${LOG_DIR}/${wname}.log"
    fi
  done

  print_title "worker 扩容完成"
  echo "  汇总       worker ${worker_running}/${workers} 运行 · $(shard_coord_backend_hint)"
  if [[ "${worker_fail}" -gt 0 ]]; then
    echo "  提示       部分 worker 未保持运行，请检查端口与日志"
  elif [[ "${worker_running}" -lt "${workers}" ]]; then
    echo "  提示       仍有 worker 未启动，可再次执行 start --workers-only"
  fi
}

cmd_start() {
  if [[ "${WORKERS_ONLY}" -eq 1 && "${HUB_ONLY}" -eq 1 ]]; then
    echo "  --workers-only 与 --hub-only 不能同时使用" >&2
    return 1
  fi
  if [[ "${HUB_ONLY}" -eq 1 ]]; then
    cmd_start_hub_only
    return
  fi
  if [[ "${WORKERS_ONLY}" -eq 1 ]]; then
    cmd_start_workers_only
    return
  fi
  local workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"
  local hub_url="http://127.0.0.1:${HUB_PORT}"

  print_title "Pallas-Bot 分片模式 · 启动"
  print_config_summary "${workers}"
  if [[ "${SKIP_OCCUPIED_PORTS}" -eq 1 ]]; then
    echo "  端口策略   自动跳过占用"
  else
    echo "  端口策略   严格 起点+分片号"
  fi
  load_shard_redis_env
  echo "  $(shard_coord_backend_hint)"
  if [[ "${PALLAS_COORD_REDIS_ENABLED:-}" == "true" ]]; then
    if ! uv run python -c "import redis" 2>/dev/null; then
      echo "  提示       请执行 uv sync --extra coord-redis 以安装 redis 客户端" >&2
    fi
  fi
  echo ""

  wait_worker_ports_released "${workers}" || true
  echo ""
  prepare_shard_ports "${workers}" || return 1
  workers="$(calc_worker_count)"
  echo ""
  echo "  正在启动进程…"

  start_hub_process

  if [[ "${DRY_RUN}" -eq 0 ]]; then
    sleep 1
  fi

  start_production_workers "${workers}"

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
    [[ "$(basename "${f}" .pid)" == "worker-test" ]] && continue
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
  echo "  汇总       hub $([[ "${hub_ok}" -eq 1 ]] && echo 运行中 || echo 未就绪) · worker ${worker_running}/${workers} 运行"
  if [[ "${hub_ok}" -eq 1 ]]; then
    echo "  WebUI      ${hub_url}/pallas/"
    echo "  协议端     ${hub_url}/protocol/console/"
  fi
  echo ""
  echo "  常用命令"
  echo "    status              查看运行状态与 Redis"
  echo "    restart --workers-only   仅重启 worker（保留 hub）"
  echo "    restart --hub-only       仅重启 hub（保留 worker）"
  echo "    test start          仅启测试 worker"
  echo "    tail -f ${LOG_DIR}/worker-0.log"
  if [[ "${worker_fail}" -gt 0 ]]; then
    echo ""
    echo "  部分 worker 未保持运行，多为端口占用或配置错误；修复后执行 restart。"
  elif [[ "${hub_ok}" -eq 1 ]] && [[ "${worker_running}" -eq "${workers}" ]]; then
    echo ""
    echo "  全部进程已就绪。"
  fi
}

cmd_stop() {
  if [[ "${WORKERS_ONLY}" -eq 1 && "${HUB_ONLY}" -eq 1 ]]; then
    echo "  --workers-only 与 --hub-only 不能同时使用" >&2
    return 1
  fi
  if [[ "${HUB_ONLY}" -eq 1 ]]; then
    local worker_counts
    worker_counts="$(count_running_production_workers)"
    local worker_running="${worker_counts%% *}"
    local worker_total="${worker_counts##* }"
    print_title "Pallas-Bot 分片模式 · 停止 hub（保留 worker）"
    if [[ "${worker_total}" -gt 0 ]]; then
      echo "  worker     保持运行（${worker_running}/${worker_total}）"
    else
      echo "  worker     未运行"
    fi
    echo ""
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      echo "  · hub  控制台：将停止（预览）"
      echo ""
      echo "  （预览模式，未实际停止进程）"
      return 0
    fi
    stop_hub_process
    echo ""
    echo "  hub 已处理完毕（生产 worker 与测试 worker-test 未停止）。"
    return 0
  fi
  if [[ "${WORKERS_ONLY}" -eq 1 ]]; then
    print_title "Pallas-Bot 分片模式 · 停止 worker（保留 hub）"
    if is_running "${PID_HUB}"; then
      echo "  hub        保持运行（端口 ${HUB_PORT}）"
    else
      echo "  hub        未运行"
    fi
    echo ""
    stop_production_workers
    echo ""
    echo "  生产 worker 已处理完毕（测试 worker-test 未停止）。"
    return 0
  fi
  print_title "Pallas-Bot 分片模式 · 停止$([[ "${FORCE_STOP}" -eq 1 ]] && echo '（强制）')"
  stop_one "worker-test" "测试 worker-test"
  stop_production_workers
  stop_hub_process
  stop_orphan_shard_processes
  echo ""
  echo "  全部分片进程已处理完毕。"
}

cmd_status() {
  local workers=0
  local running_workers=0
  local stale_workers=0
  local expected_workers
  expected_workers="$(calc_worker_count)"
  local hub_url="http://127.0.0.1:${HUB_PORT}"
  local hub_state="未运行"

  print_title "Pallas-Bot 分片模式 · 运行状态"

  echo "  配置摘要"
  print_config_summary "${expected_workers}"
  echo ""

  print_redis_status_block
  echo ""

  print_observability_status_block
  echo ""

  echo "  进程"
  if is_running "${PID_HUB}"; then
    hub_state="运行中"
    echo "    hub        ${hub_state}  :${HUB_PORT}"
    echo "               ${hub_url}/pallas/"
  else
    if [[ -f "${PID_HUB}" ]]; then
      hub_state="未运行（残留 pid）"
    fi
    echo "    hub        ${hub_state}"
  fi

  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    [[ "$(basename "${f}" .pid)" == "worker-test" ]] && continue
    workers=$((workers + 1))
    local name port state
    name="$(basename "${f}" .pid)"
    port=""
    if [[ "${name}" =~ worker-([0-9]+) ]]; then
      port="$(registry_port_for_shard "${BASH_REMATCH[1]}")"
    fi
    if is_running "${f}"; then
      running_workers=$((running_workers + 1))
      state="运行中"
    else
      stale_workers=$((stale_workers + 1))
      state="未运行"
    fi
    printf "    %-10s %-6s  WS:%s\n" "${name}" "${state}" "${port}"
  done
  if [[ "${workers}" -eq 0 && "${expected_workers}" -eq 0 ]]; then
    echo "    （尚无生产 worker，请先 start）"
  else
    echo "    小计       ${running_workers}/${expected_workers} 运行"
    if [[ "${running_workers}" -lt "${expected_workers}" ]]; then
      local sid=0 missing=0
      while [[ "${sid}" -lt "${expected_workers}" ]]; do
        local pf="${RUN_DIR}/worker-${sid}.pid"
        if ! is_running "${pf}"; then
          missing=$((missing + 1))
          local mport
          mport="$(registry_port_for_shard "${sid}")"
          echo "    worker-${sid}   未启动  WS:${mport}"
        fi
        sid=$((sid + 1))
      done
    fi
  fi

  echo ""
  echo "  测试 worker-test"
  if registry_test_enabled; then
    local tsid tport
    tsid="$(registry_test_shard_id)"
    tport="$(registry_test_port)"
    if is_running "${PID_WORKER_TEST}"; then
      echo "    状态       运行中  分片 ${tsid}  WS:${tport}"
    else
      echo "    状态       未运行  分片 ${tsid}  WS:${tport}（test start）"
    fi
  else
    echo "    状态       未配置（test init）"
  fi

  echo ""
  echo "  日志       ${LOG_DIR}/"

  if [[ "${stale_workers}" -gt 0 || "${running_workers}" -lt "${expected_workers}" ]]; then
    echo ""
    if [[ "${running_workers}" -lt "${expected_workers}" ]]; then
      echo "  提示：应有 ${expected_workers} 个 worker，当前仅 ${running_workers} 个在运行"
    else
      echo "  提示：${stale_workers} 个 worker 未运行"
    fi
    if is_running "${PID_HUB}"; then
      echo "    ./scripts/run_sharded_bot.sh start --workers-only"
      echo "    ./scripts/run_sharded_bot.sh restart --workers-only   # 需全量重启时"
    else
      echo "    ./scripts/run_sharded_bot.sh restart"
      echo "    ./scripts/run_sharded_bot.sh start --hub-only   # 仅启 WebUI 控制台"
    fi
  elif [[ "${running_workers}" -eq 0 ]] && ! is_running "${PID_HUB}"; then
    echo ""
    echo "  提示：当前无运行中的分片进程"
    echo "    ./scripts/run_sharded_bot.sh start"
  elif [[ "${running_workers}" -gt 0 ]] && ! is_running "${PID_HUB}"; then
    echo ""
    echo "  提示：worker 在运行但 hub 未运行（WebUI 不可用）"
    echo "    ./scripts/run_sharded_bot.sh start --hub-only"
  fi
}

cmd_restart_hub_only() {
  print_title "Pallas-Bot 分片模式 · 重启 hub（保留 worker）"
  echo "  hub 端口   ${HUB_PORT}"
  local worker_counts
  worker_counts="$(count_running_production_workers)"
  local worker_running="${worker_counts%% *}"
  local worker_total="${worker_counts##* }"
  if [[ "${worker_total}" -gt 0 ]]; then
    echo "  worker     保持运行（${worker_running}/${worker_total}）"
  else
    echo "  worker     未运行"
  fi
  echo ""

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "  · hub  控制台：将重启（预览）"
    echo ""
    echo "  （预览模式，未实际重启进程）"
    return 0
  fi

  stop_hub_process
  echo ""
  echo "  正在启动 hub…"
  start_hub_process

  echo ""
  echo "  正在确认 hub…"
  local hub_ok=0
  if is_running "${PID_HUB}"; then
    hub_ok=1
  else
    echo "  · 控制台 hub 未在运行，请查看日志: ${LOG_DIR}/hub.log"
  fi

  print_title "hub 重启完成"
  echo "  汇总       hub $([[ "${hub_ok}" -eq 1 ]] && echo 运行中 || echo 未就绪)"
  if [[ "${hub_ok}" -eq 1 ]]; then
    echo "  WebUI      http://127.0.0.1:${HUB_PORT}/pallas/"
  fi
  if [[ "${hub_ok}" -eq 0 ]]; then
    return 1
  fi
}

cmd_restart_workers_only() {
  local workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"

  print_title "Pallas-Bot 分片模式 · 重启 worker（保留 hub）"
  print_config_summary "${workers}"
  if is_running "${PID_HUB}"; then
    echo "  hub        保持运行（:${HUB_PORT}）"
  else
    echo "  hub        未运行（仅 worker；WebUI 需单独 start --hub-only）"
  fi
  echo ""

  stop_production_workers
  echo ""
  wait_worker_ports_released "${workers}" || true
  echo ""
  prepare_shard_ports "${workers}" || return 1
  workers="$(calc_worker_count)"
  echo ""
  echo "  正在启动 worker…"
  start_production_workers "${workers}"

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo ""
    echo "  （预览模式，未实际启动）"
    return 0
  fi

  echo ""
  echo "  正在确认 worker…"
  local worker_running=0 worker_fail=0
  local f
  for f in "${RUN_DIR}"/worker-*.pid; do
    [[ -e "${f}" ]] || continue
    [[ "$(basename "${f}" .pid)" == "worker-test" ]] && continue
    if is_running "${f}"; then
      worker_running=$((worker_running + 1))
    else
      worker_fail=$((worker_fail + 1))
      local wname
      wname="$(basename "${f}" .pid)"
      echo "  · ${wname} 启动后已退出，请查看: ${LOG_DIR}/${wname}.log"
    fi
  done

  print_title "worker 重启完成"
  load_shard_redis_env
  echo "  汇总       worker ${worker_running}/${workers} 运行 · $(shard_coord_backend_hint)"
  if [[ "${worker_fail}" -gt 0 ]]; then
    echo "  提示       部分 worker 未保持运行，请检查端口与日志"
  fi
}

cmd_restart() {
  if [[ "${WORKERS_ONLY}" -eq 1 && "${HUB_ONLY}" -eq 1 ]]; then
    echo "  --workers-only 与 --hub-only 不能同时使用" >&2
    return 1
  fi
  if [[ "${HUB_ONLY}" -eq 1 ]]; then
    cmd_restart_hub_only
    return
  fi
  if [[ "${WORKERS_ONLY}" -eq 1 ]]; then
    cmd_restart_workers_only
    return
  fi
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
    test)
      ACTION="test"
      shift
      TEST_ARGS=("$@")
      break
      ;;
    test-init|test-add|test-remove|test-list|test-sync|test-sync-ws|test-start|test-stop|test-status|test-restart)
      ACTION="test"
      sub="${1#test-}"
      if [[ "${sub}" == "sync" ]]; then
        sub="sync-ws"
      fi
      TEST_ARGS=("${sub}" "${@:2}")
      break
      ;;
    hub-start|hub-stop|hub-restart)
      ACTION="${1#hub-}"
      HUB_ONLY=1
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
    --workers-only)
      WORKERS_ONLY=1
      shift
      ;;
    --scale-only)
      SCALE_ONLY=1
      shift
      ;;
    --hub-only)
      HUB_ONLY=1
      shift
      ;;
    --force)
      FORCE_STOP=1
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

if [[ "${WORKERS_ONLY}" -eq 1 && "${HUB_ONLY}" -eq 1 ]]; then
  echo "  --workers-only 与 --hub-only 不能同时使用" >&2
  exit 1
fi

case "${ACTION}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  restart) cmd_restart ;;
  test) dispatch_test_subcmd "${TEST_ARGS[@]}" ;;
esac
