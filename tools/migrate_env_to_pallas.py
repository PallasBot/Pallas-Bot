#!/usr/bin/env python3
"""将仓库根 ``.env`` / ``.env.{ENVIRONMENT}`` 迁移为 ``config/pallas.toml`` + ``data/pallas_config/webui.json``。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.core.foundation.config.migrate_env_to_pallas import (  # noqa: E402
    EnvToPallasMigrationError,
    apply_env_to_pallas_migration,
    bootstrap_from_env,
    merge_legacy_env,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印将迁移的键数量")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 pallas.toml / webui.json")
    args = parser.parse_args()

    merged = merge_legacy_env()
    if not merged:
        print("未找到 .env 或 .env.{ENVIRONMENT}，无需迁移。", file=sys.stderr)
        return 1

    bootstrap = bootstrap_from_env(merged)
    webui_env = {
        k: v
        for k, v in merged.items()
        if k
        not in {
            "HOST",
            "PORT",
            "SUPERUSERS",
            "DB_BACKEND",
            "ACCESS_TOKEN",
            "ENVIRONMENT",
            "LOG_LEVEL",
            "MONGO_HOST",
            "MONGO_PORT",
            "MONGO_USER",
            "MONGO_PASSWORD",
            "MONGO_DB",
            "MONGO_AUTH_SOURCE",
            "PG_HOST",
            "PG_PORT",
            "PG_USER",
            "PG_PASSWORD",
            "PG_DB",
        }
    }

    if args.dry_run:
        print(f"bootstrap 字段: {len(bootstrap)} 组, webui env 键: {len(webui_env)}")
        return 0

    try:
        result = apply_env_to_pallas_migration(force=args.force)
    except EnvToPallasMigrationError as e:
        print(e.detail, file=sys.stderr)
        return 2 if e.status_code == 409 else 1

    print(f"已写入 {result.config_path}")
    print(f"已写入 {result.webui_path}（{result.webui_env_key_count} 项）")
    print("可保留 .env 专放 nb/pip 插件项；与 webui.json 避免同名键重复。示例见 .env.example。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
