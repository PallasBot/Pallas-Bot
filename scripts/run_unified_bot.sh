#!/usr/bin/env bash
# 单进程 unified 启停（兼容入口；委托 Python 实现，跨平台）
# 推荐：uv run pallas / uv run pallas run unified

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

exec uv run --no-sync python -m pallas.console.cli.unified_lifecycle "$@"
