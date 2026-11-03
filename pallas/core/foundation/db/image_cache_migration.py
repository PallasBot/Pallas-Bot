"""image_cache 存量 bytea → 文件的迁移，供 tools 脚本与启动时后台自动触发。"""

from __future__ import annotations

import asyncio
import hashlib

from nonebot import logger

from pallas.core.foundation.db.blob_store import (
    canonical_image_blob_hash,
    image_blob_is_regular_file,
    read_image_blob_at,
)

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
    from pallas.core.foundation.db.repository_pg.image_cache_repo import (
        acquire_image_blob_lock,
        image_cache_persist_blob,
    )

    if not is_pg_initialized():
        return 0
    migrated = 0
    last_log = 0

    async def migrate_candidate(row) -> int:
        data = bytes(row.blob_data)
        blob_hash = hashlib.sha256(data).hexdigest()
        async with get_session() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            await acquire_image_blob_lock(session, blob_hash)
            current = (
                await session.execute(
                    text("SELECT content_hash, blob_data, blob_path FROM image_cache WHERE id = :id FOR UPDATE"),
                    {"id": row.id},
                )
            ).first()
            if (
                current is None
                or current.blob_path is not None
                or current.blob_data is None
                or bytes(current.blob_data) != data
                or current.content_hash != row.content_hash
            ):
                return 0
            blob = image_cache_persist_blob(data, blob_hash)
            result = await session.execute(
                text(
                    "UPDATE image_cache SET content_hash = COALESCE(NULLIF(content_hash, ''), :hash), "
                    "blob_path = :path, blob_size = :size "
                    "WHERE id = :id AND blob_path IS NULL AND blob_data = :data "
                    "AND content_hash IS NOT DISTINCT FROM :old_hash"
                ),
                {
                    "hash": blob_hash,
                    "path": blob["blob_path"],
                    "size": blob["blob_size"],
                    "id": row.id,
                    "data": data,
                    "old_hash": row.content_hash,
                },
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def clear_candidate(row) -> None:
        data = bytes(row.blob_data)
        if not data:
            return
        blob_hash = hashlib.sha256(data).hexdigest()
        async with get_session() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            await acquire_image_blob_lock(session, blob_hash)
            current = (
                await session.execute(
                    text("SELECT content_hash, blob_data, blob_path FROM image_cache WHERE id = :id FOR UPDATE"),
                    {"id": row.id},
                )
            ).first()
            if (
                current is None
                or current.blob_data is None
                or bytes(current.blob_data) != data
                or current.blob_path != row.blob_path
                or current.content_hash != row.content_hash
                or canonical_image_blob_hash(current.blob_path) != blob_hash
            ):
                return
            if not await asyncio.to_thread(image_blob_is_regular_file, blob_hash):
                return
            file_data = await asyncio.to_thread(read_image_blob_at, current.blob_path)
            if file_data != data:
                return
            await session.execute(
                text(
                    "UPDATE image_cache SET blob_data = NULL WHERE id = :id AND blob_data = :data "
                    "AND blob_path = :path AND content_hash IS NOT DISTINCT FROM :old_hash"
                ),
                {"id": row.id, "data": data, "path": row.blob_path, "old_hash": row.content_hash},
            )
            await session.commit()

    while True:
        async with get_session() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
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
            await session.commit()
        if not rows:
            break

        batch_migrated = 0
        for row in rows:
            batch_migrated += await migrate_candidate(row)
        migrated += batch_migrated
        if migrated - last_log >= 2000:
            last_log = migrated
            logger.info("image_cache blob 文件迁移中 [{}] 行", migrated)
        if not batch_migrated:
            break
    if clear_blob:
        async with get_session() as session:
            max_id = int((await session.execute(text("SELECT COALESCE(MAX(id), 0) FROM image_cache"))).scalar_one())
            await session.commit()
        last_id = 0
        while last_id < max_id:
            async with get_session() as session:
                rows = (
                    await session.execute(
                        text(
                            "SELECT id, content_hash, blob_data, blob_path FROM image_cache "
                            "WHERE id > :last_id AND id <= :max_id AND blob_path IS NOT NULL "
                            "AND blob_data IS NOT NULL ORDER BY id LIMIT :limit"
                        ),
                        {"last_id": last_id, "max_id": max_id, "limit": _BATCH},
                    )
                ).all()
                await session.commit()
            if not rows:
                break
            for row in rows:
                await clear_candidate(row)
            last_id = int(rows[-1].id)
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
