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
CALC_WORKERS_SCRIPT="${SCRIPT_DIR}/calc_worker_count.py"

# shellcheck source=lib/shard_lib.sh
source "${SCRIPT_DIR}/lib/shard_lib.sh"
# shellcheck source=lib/shard_cmds.sh
source "${SCRIPT_DIR}/lib/shard_cmds.sh"


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
