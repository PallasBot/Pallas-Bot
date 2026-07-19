# Pallas-Bot 分片脚本库
[[ -n "${_PALLAS_SHARD_LIB_LOADED:-}" ]] && return 0
_PALLAS_SHARD_LIB_LOADED=1

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
  start     启动控制台与全部牛牛 worker（worker 已全部运行则跳过启动与端口重分配；可加 --hub-only / --workers-only）
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
  test2 start|stop|status|restart  第二测试 worker（worker-test2，默认 shard 98）

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
  ./scripts/run_sharded_bot.sh test2 start

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
  协议端   http://127.0.0.1:PORT/pallas/protocol/

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

require_coord_redis_for_shard_start() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  load_redis_status_lines
  local policy url pkg reachable
  policy="$(redis_status_get policy)"
  url="$(redis_status_get url)"
  pkg="$(redis_status_get package)"
  reachable="$(redis_status_get reachable)"
  if [[ "${policy}" == "false" ]]; then
    echo "  错误       分片模式依赖 Redis 协调 claim，不可禁用（PALLAS_COORD_REDIS_ENABLED=false）" >&2
    return 1
  fi
  if [[ -z "${url}" ]]; then
    echo "  错误       分片模式需要 REDIS_URL（config/pallas.toml [env] 或 webui.json）" >&2
    return 1
  fi
  if [[ "${reachable}" != "yes" ]]; then
    if [[ "${pkg}" == "no" ]]; then
      echo "  错误       Redis 客户端未安装，请执行: uv sync --extra coord-redis" >&2
    else
      echo "  错误       Redis 不可达: ${url}" >&2
      echo "  提示       请确认 Redis 服务已启动并可 ping 通" >&2
    fi
    return 1
  fi
  load_shard_redis_env
  return 0
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
  if out="$(env "${obs_env[@]}" "${START_CMD[@]}" "${status_script}" 2>/dev/null)"; then
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
  "${START_CMD[@]}" "${CALC_WORKERS_SCRIPT}" "${args[@]}" 2>/dev/null || echo 1
}

is_running() {
  local pidfile="$1"
  [[ -f "${pidfile}" ]] || return 1
  local pid
  pid="$(cat "${pidfile}" 2>/dev/null || true)"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

# 当前仓库内的 bot_hub.py / bot_worker.py（兼容相对/绝对解释器路径，不限于 uv run）
shard_pid_is_repo_python_script() {
  local pid="$1"
  local script_name="$2"
  [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  local cwd cmdline
  cwd="$(readlink -f "/proc/${pid}/cwd" 2>/dev/null || true)"
  [[ "${cwd}" == "${REPO_ROOT}" ]] || return 1
  cmdline="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true)"
  [[ "${cmdline}" == *"${script_name}"* ]] || return 1
  [[ "${cmdline}" == *python* ]] || return 1
  return 0
}

kill_repo_script_orphans() {
  local script_name="$1"
  local signal_name="$2"
  local guard="${REPO_ROOT}/scripts/shard_process_guard.py"
  if [[ -f "${guard}" ]]; then
    python3 "${guard}" --repo "${REPO_ROOT}" --script "${script_name}" --signal "${signal_name}" 2>/dev/null || true
    return 0
  fi
  local pid
  for pid in $(pgrep -f "${script_name}" 2>/dev/null || true); do
    shard_pid_is_repo_python_script "${pid}" "${script_name}" || continue
    kill "-${signal_name}" "${pid}" 2>/dev/null || true
    pkill "-${signal_name}" -P "${pid}" 2>/dev/null || true
  done
}

kill_tcp_port_listeners() {
  local port="$1"
  local signal_name="$2"
  local guard="${REPO_ROOT}/scripts/shard_process_guard.py"
  if [[ -f "${guard}" ]]; then
    python3 "${guard}" --repo "${REPO_ROOT}" --port "${port}" --signal "${signal_name}" 2>/dev/null || true
    return 0
  fi
  local pid
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] || continue
    kill "-${signal_name}" "${pid}" 2>/dev/null || true
    pkill "-${signal_name}" -P "${pid}" 2>/dev/null || true
  done < <(pids_listening_on_tcp_port "${port}")
}

tcp_port_is_listening() {
  local port="$1"
  local guard="${REPO_ROOT}/scripts/shard_process_guard.py"
  if [[ -f "${guard}" ]]; then
    [[ -n "$(python3 "${guard}" --repo "${REPO_ROOT}" --port "${port}" --list 2>/dev/null | head -n1)" ]]
    return
  fi
  local pid
  while IFS= read -r pid; do
    [[ -n "${pid}" ]] && return 0
  done < <(pids_listening_on_tcp_port "${port}")
  return 1
}

pids_listening_on_tcp_port() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -tlnp "sport = :${port}" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null | sort -u
  fi
}

format_port_listener_hint() {
  local port="$1"
  local pid cmdline
  for pid in $(pids_listening_on_tcp_port "${port}"); do
    [[ -n "${pid}" ]] || continue
    cmdline="$(tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || echo "?")"
    echo "      pid ${pid}: ${cmdline}"
  done
}

require_tcp_port_free() {
  local port="$1"
  local label="$2"
  if ! tcp_port_is_listening "${port}"; then
    return 0
  fi
  echo "  · ${label}：端口 ${port} 仍被占用，无法启动" >&2
  format_port_listener_hint "${port}" >&2
  return 1
}

kill_registered_worker_port_listeners() {
  local signal_name="$1"
  local workers sid wport
  workers="${WORKER_COUNT_OVERRIDE:-$(calc_worker_count)}"
  sid=0
  while [[ "${sid}" -lt "${workers}" ]]; do
    wport="$(worker_port_for_sid "${sid}")"
    kill_tcp_port_listeners "${wport}" "${signal_name}"
    sid=$((sid + 1))
  done
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
# 主日志由进程内 loguru 写入 ${logfile}；bootstrap 仅捕获 init 前/崩溃输出
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

# 清理无 pid 文件或 pid 已过期的孤儿进程（按仓库 cwd + 端口兜底）
stop_orphan_shard_processes() {
  stop_orphan_hub_processes
  stop_orphan_worker_processes
}

stop_orphan_worker_processes() {
  local sig=TERM
  [[ "${FORCE_STOP}" -eq 1 ]] && sig=KILL
  kill_repo_script_orphans "bot_worker.py" "${sig}"
  kill_registered_worker_port_listeners "${sig}"
  if [[ "${FORCE_STOP}" -eq 1 ]]; then
    return 0
  fi
  sleep 1
  kill_repo_script_orphans "bot_worker.py" "KILL"
  kill_registered_worker_port_listeners "KILL"
}

stop_orphan_hub_processes() {
  local sig=TERM
  [[ "${FORCE_STOP}" -eq 1 ]] && sig=KILL
  kill_repo_script_orphans "bot_hub.py" "${sig}"
  kill_tcp_port_listeners "${HUB_PORT}" "${sig}"
  if [[ "${FORCE_STOP}" -eq 1 ]]; then
    return 0
  fi
  sleep 1
  kill_repo_script_orphans "bot_hub.py" "KILL"
  kill_tcp_port_listeners "${HUB_PORT}" "KILL"
}

start_hub_process() {
  require_tcp_port_free "${HUB_PORT}" "hub  控制台" || return 1
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
    case "$(basename "${f}" .pid)" in worker-test|worker-test2) continue ;; esac
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
    case "$(basename "${f}" .pid)" in worker-test|worker-test2) continue ;; esac
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
    require_tcp_port_free "${wport}" "worker-${sid}  WS:${wport}" || return 1
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
    require_tcp_port_free "${wport}" "worker-${sid}  WS:${wport}" || return 1
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
    case "$(basename "${f}" .pid)" in
      worker-test|worker-test2) continue ;;
    esac
    if is_running "${f}"; then
      running=$((running + 1))
    fi
  done
  echo "${running}"
}

# cold=冷启动（评估端口并同步协议端）；scale=仅补缺失 worker；skip=已全部运行
resolve_production_worker_start_mode() {
  local workers="$1"
  local running
  running="$(count_running_production_worker_ids)"
  if [[ "${workers}" -le 0 ]]; then
    echo "cold"
  elif [[ "${running}" -ge "${workers}" ]]; then
    echo "skip"
  elif [[ "${running}" -gt 0 ]]; then
    echo "scale"
  else
    echo "cold"
  fi
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
  if "${START_CMD[@]}" "${WAIT_PORTS_SCRIPT}" \
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
  out="$("${START_CMD[@]}" "${STARTUP_PORTS_SCRIPT}" "${prep_args[@]}" 2>&1)" || rc=$?
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
  out="$("${START_CMD[@]}" "${ALLOC_PORTS_SCRIPT}" "${alloc_args[@]}" 2>&1)" || rc=$?
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
  "${START_CMD[@]}" "${SYNC_PORTS_SCRIPT}" \
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
  "${START_CMD[@]}" "${SHARD_TEST_SCRIPT}" --env "${REPO_ROOT}/.env" --accounts "${ACCOUNTS_JSON}" "$@"
}

cmd_test_start() {
  if ! registry_test_enabled; then
    echo "  测试分片未启用。请先执行: ./scripts/run_sharded_bot.sh test init" >&2
    return 1
  fi
  require_coord_redis_for_shard_start || return 1

  local tsid tport
  tsid="$(registry_test_shard_id)"
  tport="$(registry_test_port)"
  print_title "Pallas-Bot 测试 worker · 启动"
  echo "  测试分片 id=${tsid}，WS 端口 ${tport}"
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

registry_test2_port() {
  python3 - "${REGISTRY_JSON}" "${TEST2_SHARD_ID}" <<'PY' 2>/dev/null
import json, sys
from pathlib import Path
raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
want = int(sys.argv[2])
for row in raw.get("shards") or []:
    if int(row.get("id", -1)) == want:
        print(int(row.get("port") or 0))
        break
else:
    print(0)
PY
}

cmd_test2_start() {
  require_coord_redis_for_shard_start || return 1

  local tsid tport
  tsid="${TEST2_SHARD_ID}"
  tport="$(registry_test2_port)"
  if [[ -z "${tport}" || "${tport}" -le 0 ]]; then
    echo "  未找到 test2 分片（id=${tsid}）端口，请检查 registry.json" >&2
    return 1
  fi
  print_title "Pallas-Bot 测试 worker2 · 启动"
  echo "  测试分片 id=${tsid}，WS 端口 ${tport}"
  echo "  $(shard_coord_backend_hint)"
  echo ""
  local common=(
    PALLAS_SHARD_ENABLED=true
    PALLAS_SHARD_BOTS_PER="${BOTS_PER_SHARD}"
    PALLAS_SHARD_HUB_PORT="${HUB_PORT}"
    PALLAS_SHARD_WORKER_BASE_PORT="${WORKER_BASE_PORT}"
  )
  start_one "worker-test2" "测试 worker-test2（WS 端口 ${tport}）" env \
    "${common[@]}" \
    PALLAS_BOT_ROLE=worker \
    PALLAS_SHARD_ID="${tsid}" \
    PORT="${tport}" \
    "${START_CMD[@]}" bot_worker.py
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    return 0
  fi
  if is_running "${PID_WORKER_TEST2}"; then
    echo ""
    echo "  测试 worker2 已就绪。日志: ${LOG_DIR}/worker-test2.log"
  else
    echo ""
    echo "  测试 worker2 启动后已退出，请查看: ${LOG_DIR}/worker-test2.log"
    return 1
  fi
}

cmd_test2_stop() {
  print_title "Pallas-Bot 测试 worker2 · 停止"
  stop_one "worker-test2" "测试 worker-test2"
}

cmd_test2_status() {
  print_title "Pallas-Bot 测试 worker2 · 状态"
  local tsid tport
  tsid="${TEST2_SHARD_ID}"
  tport="$(registry_test2_port)"
  echo "  分片 id=${tsid}，WS 端口 ${tport:-?}"
  echo ""
  if is_running "${PID_WORKER_TEST2}"; then
    echo "  进程：运行中（worker-test2）"
    echo "  日志：${LOG_DIR}/worker-test2.log"
  else
    echo "  进程：未运行"
    echo "  启动：./scripts/run_sharded_bot.sh test2 start"
  fi
}

cmd_test2_restart() {
  cmd_test2_stop
  echo ""
  cmd_test2_start
}

dispatch_test2_subcmd() {
  local sub="${1:-}"
  shift || true
  case "${sub}" in
    start) cmd_test2_start ;;
    stop) cmd_test2_stop ;;
    status) cmd_test2_status ;;
    restart) cmd_test2_restart ;;
    "")
      echo "用法: test2 <start|stop|status|restart>" >&2
      return 1
      ;;
    *)
      echo "未知 test2 子命令: ${sub}" >&2
      return 1
      ;;
  esac
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
