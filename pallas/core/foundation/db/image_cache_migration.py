"""image_cache 存量 bytea → 文件的迁移，供 tools 脚本与启动时后台自动触发。"""

from __future__ import annotations

import asyncio
import hashlib

from nonebot import logger

from pallas.core.foundation.db.blob_store import image_blob_rel_path, write_image_blob

_BATCH = 200


async def pending_image_cache_blob_migration_count() -> int:
    """还有多少行 blob 未落文件（断点续传依据）。"""
    from sqlalchemy import text

    from pallas.core.foundation.db.repository_pg import get_session, is_pg_initialized

    if not is_pg_initialized():
        return 0
    async with get_session(read_only=True) as session:
        result = await session.execute(
            text(
                "SELECT count(*) FROM image_cache "
                "WHERE blob_data IS NOT NULL AND octet_length(blob_data) > 0 AND blob_path IS NULL"
            )
        )
        return int(result.scalar_one())


async def migrate_image_cache_blobs(*, clear_blob: bool = False) -> int:
    """把存量 blob_data 导出到文件并回填元数据，逐批提交，断点续传。返回迁移行数。"""
    from sqlalchemy import text

    from pallas.core.foundation.db.repository_pg import get_session, is_pg_initialized

    if not is_pg_initialized():
        return 0
    migrated = 0
    last_log = 0
    async with get_session() as session:
        while True:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, content_hash, blob_data FROM image_cache "
                        "WHERE blob_data IS NOT NULL AND octet_length(blob_data) > 0 AND blob_path IS NULL "
                        "ORDER BY id LIMIT :limit"
                    ),
                    {"limit": _BATCH},
                )
            ).all()
            if not rows:
                break
            for row in rows:
                data = bytes(row.blob_data)
                content_hash = row.content_hash or hashlib.sha256(data).hexdigest()
                write_image_blob(content_hash, data)
                await session.execute(
                    text(
                        "UPDATE image_cache SET content_hash = COALESCE(content_hash, :hash), "
                        "blob_path = :path, blob_size = :size WHERE id = :id"
                    ),
                    {
                        "hash": content_hash,
                        "path": str(image_blob_rel_path(content_hash)),
                        "size": len(data),
                        "id": row.id,
                    },
                )
            await session.commit()
            migrated += len(rows)
            if migrated - last_log >= 2000:
                last_log = migrated
                logger.info("image_cache blob 文件迁移中 [{}] 行", migrated)
        if clear_blob:
            await session.execute(
                text("UPDATE image_cache SET blob_data = NULL WHERE blob_path IS NOT NULL AND blob_data IS NOT NULL")
            )
            await session.commit()
    return migrated


async def ensure_image_cache_blob_migration_started() -> bool:
    """检测存量未迁移数据，若有则后台执行迁移，不阻塞启动。返回是否已启动。"""
    from pallas.core.foundation.db.repository_pg import is_pg_initialized

    if not is_pg_initialized():
        return False
    try:
        pending = await pending_image_cache_blob_migration_count()
    except Exception:  # noqa: BLE001
        return False
    if pending <= 0:
        return False
    logger.info("image_cache blob 文件迁移待处理 [{}] 行，后台执行", pending)
    asyncio.create_task(_run_background_migration(), name="image_cache_blob_file_migration")
    return True


async def _run_background_migration() -> None:
    try:
        migrated = await migrate_image_cache_blobs()
        logger.info("image_cache blob 文件迁移完成 [{}] 行", migrated)
    except Exception:  # noqa: BLE001
        logger.exception("image_cache blob 文件迁移失败")
