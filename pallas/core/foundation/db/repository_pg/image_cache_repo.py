"""PostgreSQL ImageCache Repository"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, case, delete, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from pallas.core.foundation.db import repository_pg as _repo
from pallas.core.foundation.db.blob_store import (
    delete_image_blob,
    image_blob_rel_path,
    read_image_blob_at,
    write_image_blob,
)
from pallas.core.foundation.db.repository_pg.lifecycle import _s
from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

if TYPE_CHECKING:
    from pallas.core.foundation.db.modules import ImageCache


def row_to_image_cache(row: ImageCacheRow) -> ImageCache:
    from pallas.core.foundation.db.modules import ImageCache

    return ImageCache.model_construct(
        cq_code=row.cq_code,
        content_hash=row.content_hash,
        blob_data=row.blob_data,
        blob_path=row.blob_path,
        blob_size=row.blob_size,
        ref_times=row.ref_times,
        date=row.date,
    )


def image_cache_has_blob_clause():
    """迁移期兼容：文件化后走 blob_path，存量旧行 blob_data 仍有效。"""
    return or_(
        ImageCacheRow.blob_path.is_not(None),
        and_(ImageCacheRow.blob_data.is_not(None), ImageCacheRow.blob_data != b""),
    )


def image_cache_persist_blob(cache: ImageCache) -> dict[str, Any]:
    """blob_data 有值时写文件，返回入库用的 content_hash/blob_path/blob_size。"""
    data = cache.blob_data
    if not data:
        return {}
    content_hash = cache.content_hash or hashlib.sha256(data).hexdigest()
    return {
        "content_hash": content_hash,
        "blob_path": str(image_blob_rel_path(content_hash)),
        "blob_size": write_image_blob(content_hash, data),
    }


async def image_cache_cleanup_blobs(hashes: list[str | None]) -> None:
    present = {h for h in hashes if h}
    if not present:
        return
    async with _repo.get_session(read_only=True) as session:
        rows = (
            (
                await session.execute(
                    select(ImageCacheRow.content_hash).where(ImageCacheRow.content_hash.in_(tuple(present))).distinct()
                )
            )
            .scalars()
            .all()
        )
    referenced = set(rows)
    for content_hash in present - referenced:
        delete_image_blob(content_hash)


async def image_cache_fill_blob(cache: ImageCache | None):
    """返回前把文件 blob 装入内存，兼容直接调 repo 的消费方与迁移期旧行。"""
    if cache is None or cache.blob_data or not cache.blob_path:
        return cache
    cache.blob_data = await asyncio.to_thread(read_image_blob_at, cache.blob_path)
    return cache


class PgImageCacheRepository:
    async def find_by_cq_code(self, cq_code: str):
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == cq_code))
            row = result.scalar_one_or_none()
            return await image_cache_fill_blob(row_to_image_cache(row) if row else None)

    async def find_by_content_hash(self, content_hash: str):
        async with _repo.get_session(read_only=True) as session:
            stmt = (
                select(ImageCacheRow)
                .where(ImageCacheRow.content_hash == content_hash)
                .order_by(ImageCacheRow.date.desc(), ImageCacheRow.id.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            return await image_cache_fill_blob(row_to_image_cache(row) if row else None)

    async def find_by_url(self, url: str):
        async with _repo.get_session(read_only=True) as session:
            stmt = (
                select(ImageCacheRow)
                .where(ImageCacheRow.cq_code.contains(url), image_cache_has_blob_clause())
                .order_by(ImageCacheRow.date.desc(), ImageCacheRow.id.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalars().first()
            return await image_cache_fill_blob(row_to_image_cache(row) if row else None)

    async def bind_content_hash(self, cq_code: str, content_hash: str) -> None:
        async with _repo.get_session() as session:
            await session.execute(
                update(ImageCacheRow).where(ImageCacheRow.cq_code == cq_code).values(content_hash=content_hash)
            )
            await session.commit()

    async def find_latest_with_blob(self):
        async with _repo.get_session(read_only=True) as session:
            stmt = (
                select(ImageCacheRow)
                .where(image_cache_has_blob_clause())
                .order_by(ImageCacheRow.date.desc(), ImageCacheRow.id.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            return await image_cache_fill_blob(row_to_image_cache(row) if row else None)

    async def find_recent_with_blob(self, limit: int) -> list:
        async with _repo.get_session(read_only=True) as session:
            stmt = (
                select(ImageCacheRow)
                .where(image_cache_has_blob_clause())
                .order_by(ImageCacheRow.date.desc(), ImageCacheRow.id.desc())
                .limit(max(1, int(limit)))
            )
            rows = (await session.execute(stmt)).scalars().all()
        caches = [row_to_image_cache(row) for row in rows]
        return [cache for cache in await asyncio.gather(*(image_cache_fill_blob(c) for c in caches)) if cache]

    async def insert(self, cache) -> None:
        """并发下相同 cq_code 的第二次 insert 等价为 no-op。"""
        blob = image_cache_persist_blob(cache)
        values: dict[str, Any] = {
            "cq_code": _s(cache.cq_code) or "",
            "content_hash": _s(blob.get("content_hash") or cache.content_hash),
            "blob_path": blob.get("blob_path"),
            "blob_size": blob.get("blob_size"),
            "ref_times": cache.ref_times,
            "date": cache.date,
        }
        # 迁移期：blob 尚未文件化时沿用旧 bytea 列
        if not blob and cache.blob_data:
            values["blob_data"] = cache.blob_data
        async with _repo.get_session() as session:
            stmt = pg_insert(ImageCacheRow).values(values)
            await session.execute(stmt.on_conflict_do_nothing(index_elements=["cq_code"]))
            await session.commit()

    async def save(self, cache) -> None:
        """upsert 语义：存在则更新，否则插入。"""
        blob = image_cache_persist_blob(cache)
        values: dict[str, Any] = {
            "cq_code": _s(cache.cq_code) or "",
            "content_hash": _s(blob.get("content_hash") or cache.content_hash),
            "blob_path": blob.get("blob_path"),
            "blob_size": blob.get("blob_size"),
            "ref_times": cache.ref_times,
            "date": cache.date,
        }
        if not blob and cache.blob_data:
            values["blob_data"] = cache.blob_data
        async with _repo.get_session() as session:
            stmt = pg_insert(ImageCacheRow).values(values)
            set_ = {
                "ref_times": stmt.excluded.ref_times,
                "date": stmt.excluded.date,
                "content_hash": stmt.excluded.content_hash,
                "blob_path": stmt.excluded.blob_path,
                "blob_size": stmt.excluded.blob_size,
            }
            if not blob:
                set_["blob_data"] = stmt.excluded.blob_data
            stmt = stmt.on_conflict_do_update(index_elements=["cq_code"], set_=set_)
            await session.execute(stmt)
            await session.commit()

    async def touch(self, cq_code: str, *, date: int) -> None:
        async with _repo.get_session() as session:
            await session.execute(
                update(ImageCacheRow)
                .where(ImageCacheRow.cq_code == cq_code)
                .values(ref_times=ImageCacheRow.ref_times + 1, date=int(date))
            )
            await session.commit()

    async def delete_old(self, before_date: int) -> None:
        while True:
            async with _repo.get_session(read_only=True) as session:
                rows = (
                    await session.execute(
                        select(ImageCacheRow.id, ImageCacheRow.content_hash)
                        .where(ImageCacheRow.date < int(before_date))
                        .limit(1000)
                    )
                ).all()
            if not rows:
                break
            ids = [int(row[0]) for row in rows]
            async with _repo.get_session() as session:
                await session.execute(delete(ImageCacheRow).where(ImageCacheRow.id.in_(ids)))
                await session.commit()
            await image_cache_cleanup_blobs([str(row[1]) for row in rows])
            if len(rows) < 1000:
                break

    async def delete_low_ref(self, ref_threshold: int) -> None:
        while True:
            async with _repo.get_session(read_only=True) as session:
                rows = (
                    await session.execute(
                        select(ImageCacheRow.id, ImageCacheRow.content_hash)
                        .where(ImageCacheRow.ref_times < ref_threshold)
                        .limit(1000)
                    )
                ).all()
            if not rows:
                break
            ids = [int(row[0]) for row in rows]
            async with _repo.get_session() as session:
                await session.execute(delete(ImageCacheRow).where(ImageCacheRow.id.in_(ids)))
                await session.commit()
            await image_cache_cleanup_blobs([str(row[1]) for row in rows])
            if len(rows) < 1000:
                break

    async def prune(self, policy) -> Any:
        from pallas.core.foundation.db.repository import ImageCachePruneResult

        batch_size = max(1, int(policy.batch_size))
        max_blob_bytes = max(0, int(policy.max_blob_bytes))
        deleted_rows = 0
        deleted_blob_bytes = 0
        blob_size_expr = func.coalesce(
            ImageCacheRow.blob_size,
            func.pg_column_size(ImageCacheRow.blob_data),
            0,
        )

        async def total_blob_bytes() -> int:
            async with _repo.get_session(read_only=True) as session:
                stmt = select(func.coalesce(func.sum(blob_size_expr), 0))
                return int((await session.execute(stmt)).scalar_one())

        async def delete_batch(where_clause, *, size_limit: int | None = None) -> tuple[int, int]:
            async with _repo.get_session(read_only=True) as session:
                stmt = (
                    select(ImageCacheRow.id, ImageCacheRow.content_hash, blob_size_expr)
                    .where(where_clause)
                    .order_by(
                        case((ImageCacheRow.ref_times <= 1, 0), else_=1),
                        ImageCacheRow.date,
                        ImageCacheRow.id,
                    )
                    .limit(batch_size)
                )
                rows = list((await session.execute(stmt)).all())
                if size_limit is not None:
                    selected = []
                    selected_bytes = 0
                    for row in rows:
                        selected.append(row)
                        selected_bytes += int(row[2])
                        if selected_bytes >= size_limit:
                            break
                    rows = selected
                if not rows:
                    return 0, 0
                ids = [int(row[0]) for row in rows]
                hashes = [str(row[1]) for row in rows]
            async with _repo.get_session() as session:
                await session.execute(delete(ImageCacheRow).where(ImageCacheRow.id.in_(ids)))
                await session.commit()
            await image_cache_cleanup_blobs(hashes)
            return len(rows), sum(int(row[2]) for row in rows)

        expired = or_(
            ImageCacheRow.date < int(policy.absolute_before),
            and_(ImageCacheRow.date < int(policy.single_use_before), ImageCacheRow.ref_times <= 1),
        )
        while True:
            rows, blob_bytes = await delete_batch(expired)
            deleted_rows += rows
            deleted_blob_bytes += blob_bytes
            if rows < batch_size:
                break

        remaining_blob_bytes = await total_blob_bytes()
        while remaining_blob_bytes > max_blob_bytes:
            rows, blob_bytes = await delete_batch(
                literal_column("true"),
                size_limit=remaining_blob_bytes - max_blob_bytes,
            )
            if not rows:
                break
            deleted_rows += rows
            deleted_blob_bytes += blob_bytes
            remaining_blob_bytes = max(0, remaining_blob_bytes - blob_bytes)

        return ImageCachePruneResult(
            deleted_rows=deleted_rows,
            deleted_blob_bytes=deleted_blob_bytes,
            remaining_blob_bytes=remaining_blob_bytes,
        )
