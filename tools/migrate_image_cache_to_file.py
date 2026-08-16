#!/usr/bin/env python3
"""把 image_cache 存量 bytea 导出到本地文件，DB 只留元数据。

用法：
  uv run python tools/migrate_image_cache_to_file.py             # 迁移存量（断点续传）
  uv run python tools/migrate_image_cache_to_file.py --clear-blob  # 迁移完成后清空 blob_data 列
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def apply_repo_settings() -> None:
    try:
        from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ

        apply_repo_settings_to_environ()
    except Exception as e:  # noqa: BLE001
        print(f"[env] 合并仓库配置失败，继续使用现有环境变量: {e}")


def _pg_dsn() -> str:
    host = os.environ.get("PG_HOST", "127.0.0.1")
    port = os.environ.get("PG_PORT", "5432")
    user = os.environ.get("PG_USER", "")
    password = os.environ.get("PG_PASSWORD", "")
    db = os.environ.get("PG_DB", "PallasBot")
    auth = f"{quote_plus(user)}:{quote_plus(password)}@" if user and password else ""
    return f"postgresql+asyncpg://{auth}{host}:{port}/{db}"


async def run() -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    from pallas.core.foundation.db.image_cache_migration import migrate_image_cache_blobs
    from pallas.core.foundation.db.repository_pg import dispose_pg, init_pg

    clear_blob = "--clear-blob" in sys.argv
    engine = create_async_engine(_pg_dsn())
    try:
        await init_pg(engine)
        from pallas.core.foundation.db.image_cache_migration import pending_image_cache_blob_migration_count

        pending = await pending_image_cache_blob_migration_count()
        if pending:
            print(f"待迁移 {pending} 行")
        migrated = await migrate_image_cache_blobs(clear_blob=clear_blob)
        if clear_blob:
            print(f"迁移完成：文件化 {migrated} 行，已清空 blob_data 列")
        else:
            print(f"迁移完成：文件化 {migrated} 行，可加 --clear-blob 清空 DB 大字段")
        return migrated
    finally:
        await dispose_pg()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    apply_repo_settings()
    main()
