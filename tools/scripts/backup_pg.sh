#!/usr/bin/env bash
# PostgreSQL 逻辑备份
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
if command -v uv >/dev/null 2>&1; then
  exec uv run python tools/scripts/backup_pg.py "$@"
fi
exec python tools/scripts/backup_pg.py "$@"
