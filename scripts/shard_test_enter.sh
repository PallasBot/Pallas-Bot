#!/usr/bin/env bash
# 进入分片测试环境：主仓 .env、data 共用、协议端 ws_url 迁到 worker 端口。
#
#   ./scripts/shard_test_enter.sh
#   ./scripts/shard_test_enter.sh --main-repo /path/to/Pallas-Bot
#
# 测试结束后执行: ./scripts/shard_test_leave.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

MAIN_REPO="${PALLAS_MAIN_REPO:-$(cd "${REPO_ROOT}/.." && pwd)/Pallas-Bot}"
# 状态与备份放在仓库根，避免 data 改符号链接后路径漂到主仓
STATE_ROOT="${REPO_ROOT}/.shard_test_state"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${STATE_ROOT}/backups/${STAMP}"
STATE_FILE="${STATE_ROOT}/active.json"

usage() {
  cat <<EOF
用法: shard_test_enter.sh [--main-repo PATH] [--skip-port-migrate] [--dry-run]

  --main-repo PATH     主仓 Pallas-Bot 路径（默认: ${REPO_ROOT}/../Pallas-Bot）
  --skip-port-migrate  仅 .env + data，不改 accounts.json
  --dry-run            只打印将执行的操作
EOF
}

SKIP_MIGRATE=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --main-repo)
      MAIN_REPO="$(cd "$2" && pwd)"
      shift 2
      ;;
    --skip-port-migrate)
      SKIP_MIGRATE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "${MAIN_REPO}" ]]; then
  echo "主仓不存在: ${MAIN_REPO}" >&2
  exit 1
fi

if [[ ! -f "${MAIN_REPO}/.env" ]]; then
  echo "主仓缺少 .env: ${MAIN_REPO}/.env" >&2
  exit 1
fi

if [[ -f "${STATE_FILE}" ]]; then
  echo "已在测试模式（${STATE_FILE} 存在）。请先执行: ./scripts/shard_test_leave.sh" >&2
  exit 1
fi

MAIN_DATA="${MAIN_REPO}/data"
ACCOUNTS_JSON="${MAIN_DATA}/pallas_protocol/accounts.json"
REGISTRY_JSON="${MAIN_DATA}/pallas_shard/registry.json"

run() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

echo "主仓: ${MAIN_REPO}"
echo "分片仓: ${REPO_ROOT}"
echo "备份目录: ${BACKUP_DIR}"

if [[ "${DRY_RUN}" -eq 0 ]]; then
  mkdir -p "${BACKUP_DIR}"
fi

# 1) 备份分片仓 .env
if [[ -f "${REPO_ROOT}/.env" ]]; then
  run cp -a "${REPO_ROOT}/.env" "${BACKUP_DIR}/env.shard.orig"
fi

# 2) 使用主仓 .env，并追加分片开关（不覆盖主仓已有键）
run cp -a "${MAIN_REPO}/.env" "${REPO_ROOT}/.env"
append_shard_env() {
  local key="$1" val="$2"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] append ${key}=${val}"
    return
  fi
  if ! grep -q "^${key}=" "${REPO_ROOT}/.env" 2>/dev/null; then
    echo "${key}=${val}" >> "${REPO_ROOT}/.env"
  fi
}
if [[ "${DRY_RUN}" -eq 0 ]]; then
  {
    echo ""
    echo "# --- shard_test_enter.sh 追加（测试结束请 leave 还原）---"
  } >> "${REPO_ROOT}/.env"
fi
append_shard_env PALLAS_SHARD_ENABLED true
append_shard_env PALLAS_SHARD_HUB_PORT 8088
append_shard_env PALLAS_SHARD_WORKER_BASE_PORT 8090
append_shard_env PALLAS_SHARD_BOTS_PER 5

# 3) data -> 主仓 data（符号链接）
DATA_BACKUP=""
if [[ -L "${REPO_ROOT}/data" ]]; then
  echo "data 已是符号链接，将替换为指向主仓" >&2
  run rm "${REPO_ROOT}/data"
elif [[ -e "${REPO_ROOT}/data" ]]; then
  DATA_BACKUP="${REPO_ROOT}/data.pre_shard_test.${STAMP}"
  echo "备份分片仓原 data -> ${DATA_BACKUP}"
  if pgrep -f "${REPO_ROOT}.*bot_(hub|worker)\.py" >/dev/null 2>&1; then
    echo "提示: 检测到 hub/worker 在运行，mv 可能较慢；建议先 ./scripts/run_sharded_bot.sh stop" >&2
  fi
  echo "正在移动 data 目录…"
  run mv "${REPO_ROOT}/data" "${DATA_BACKUP}"
  echo "data 已移至 ${DATA_BACKUP}"
fi
echo "正在链接 data -> ${MAIN_DATA}"
run ln -sfn "${MAIN_DATA}" "${REPO_ROOT}/data"

# 4) 协议端端口迁移
ACCOUNTS_BACKUP="${BACKUP_DIR}/accounts.json.pre_test"
REGISTRY_BACKUP=""
if [[ -f "${REGISTRY_JSON}" ]]; then
  REGISTRY_BACKUP="${BACKUP_DIR}/registry.json.pre_test"
  run cp -a "${REGISTRY_JSON}" "${REGISTRY_BACKUP}"
fi

if [[ "${SKIP_MIGRATE}" -eq 0 ]]; then
  if [[ ! -f "${ACCOUNTS_JSON}" ]]; then
    echo "警告: 未找到 ${ACCOUNTS_JSON}，跳过端口迁移" >&2
  elif [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] uv run python scripts/shard_test_migrate_ports.py --apply --backup ${ACCOUNTS_BACKUP}"
  else
    echo "正在迁移协议端 accounts.json 端口（uv run，首次可能需数秒）…"
    uv run python scripts/shard_test_migrate_ports.py \
      --apply \
      --accounts "${ACCOUNTS_JSON}" \
      --backup "${ACCOUNTS_BACKUP}" \
      --env "${REPO_ROOT}/.env"
  fi
else
  echo "已跳过端口迁移（--skip-port-migrate）"
fi

if [[ "${DRY_RUN}" -eq 0 ]]; then
  python3 - <<PY
import json
from pathlib import Path
state = {
    "stamp": "${STAMP}",
    "main_repo": "${MAIN_REPO}",
    "backup_dir": "${BACKUP_DIR}",
    "data_backup": "${DATA_BACKUP}",
    "accounts_backup": "${ACCOUNTS_BACKUP}",
    "registry_backup": "${REGISTRY_BACKUP}",
}
Path("${STATE_FILE}").parent.mkdir(parents=True, exist_ok=True)
Path("${STATE_FILE}").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
fi

echo ""
echo "已进入分片测试模式。"
echo "  data -> ${MAIN_DATA}"
echo "  .env <- ${MAIN_REPO}/.env（已追加分片变量）"
echo "  状态: ${STATE_FILE}"
echo ""
echo "下一步:"
echo "  uv sync --extra pg   # 若用 PostgreSQL 且尚未安装"
echo "  ./scripts/run_sharded_bot.sh start"
echo "  协议端账号需在控制台「重启」使新 ws_url 生效"
echo ""
echo "结束后: ./scripts/shard_test_leave.sh"
