#!/usr/bin/env bash
# 分片启停：生产路径委托 Python（跨平台）；test/test2 仍走 legacy bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

needs_legacy=0
for arg in "$@"; do
  case "${arg}" in
    test|test2|test-*|test2-*) needs_legacy=1 ;;
  esac
done

if [[ "${needs_legacy}" -eq 1 ]]; then
  exec bash "${SCRIPT_DIR}/lib/run_sharded_bot_legacy.sh" "$@"
fi

exec uv run --no-sync python -m pallas.console.cli.shard_lifecycle "$@"
