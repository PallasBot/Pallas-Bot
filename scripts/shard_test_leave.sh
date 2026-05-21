#!/usr/bin/env bash
# 退出分片测试：恢复 .env、data 链接、协议端 accounts.json（及 registry）。
#
#   ./scripts/shard_test_leave.sh
# 建议先: ./scripts/run_sharded_bot.sh stop

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

STATE_ROOT="${REPO_ROOT}/.shard_test_state"
STATE_FILE="${STATE_ROOT}/active.json"

if [[ ! -f "${STATE_FILE}" ]]; then
  echo "未找到测试状态 ${STATE_FILE}，无需还原或从未执行 enter。" >&2
  exit 1
fi

eval "$(STATE_FILE="${STATE_FILE}" python3 - <<'PY'
import json
import os
from pathlib import Path

s = json.loads(Path(os.environ["STATE_FILE"]).read_text(encoding="utf-8"))
for k, v in s.items():
    if v is None:
        v = ""
    v = str(v).replace('"', '\\"')
    print(f'{k}="{v}"')
PY
)"

echo "还原测试环境 (stamp=${stamp})"

# 停分片进程（忽略失败）
if [[ -x "${REPO_ROOT}/scripts/run_sharded_bot.sh" ]]; then
  "${REPO_ROOT}/scripts/run_sharded_bot.sh" stop 2>/dev/null || true
fi

# 1) 恢复 accounts.json
if [[ -n "${accounts_backup}" && -f "${accounts_backup}" ]]; then
  target="${REPO_ROOT}/data/pallas_protocol/accounts.json"
  if [[ -L "${REPO_ROOT}/data" ]]; then
    target="$(readlink -f "${REPO_ROOT}/data")/pallas_protocol/accounts.json"
  fi
  cp -a "${accounts_backup}" "${target}"
  echo "已恢复 accounts.json -> ${target}"
fi

# 2) 恢复 registry.json（若有备份）
if [[ -n "${registry_backup}" && -f "${registry_backup}" ]]; then
  reg_target="${REPO_ROOT}/data/pallas_shard/registry.json"
  if [[ -L "${REPO_ROOT}/data" ]]; then
    reg_target="$(readlink -f "${REPO_ROOT}/data")/pallas_shard/registry.json"
  fi
  cp -a "${registry_backup}" "${reg_target}"
  echo "已恢复 registry.json"
fi

# 3) 还原 data 目录
if [[ -L "${REPO_ROOT}/data" ]]; then
  rm "${REPO_ROOT}/data"
  echo "已移除 data 符号链接"
fi
if [[ -n "${data_backup}" && -d "${data_backup}" ]]; then
  mv "${data_backup}" "${REPO_ROOT}/data"
  echo "已还原分片仓 data <- ${data_backup}"
elif [[ ! -e "${REPO_ROOT}/data" ]]; then
  mkdir -p "${REPO_ROOT}/data"
  echo "已创建空 data 目录"
fi

# 4) 还原 .env
if [[ -f "${backup_dir}/env.shard.orig" ]]; then
  cp -a "${backup_dir}/env.shard.orig" "${REPO_ROOT}/.env"
  echo "已还原 .env <- env.shard.orig"
else
  echo "无 env.shard.orig 备份，保留当前 .env（请自行确认）" >&2
fi

rm -f "${STATE_FILE}"
echo ""
echo "已退出分片测试模式。"
echo "主仓数据与协议端 ws_url 已按备份还原；请重启主仓单进程 Bot 与协议端账号（若曾在测试中改过端口）。"
