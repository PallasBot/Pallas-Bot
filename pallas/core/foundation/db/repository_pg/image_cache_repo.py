"""PostgreSQL ImageCache Repository"""

from __future__ import annotations

import asyncio
import hashlib
import stat
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, case, delete, func, literal_column, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from pallas.core.foundation.db import repository_pg as _repo
from pallas.core.foundation.db.blob_store import (
    canonical_image_blob_hash,
    delete_image_blob,
    image_blob_abs_path,
    image_blob_rel_path,
    image_blob_size,
    read_image_blob_at,
    write_image_blob,
)
from pallas.core.foundation.db.repository_pg.lifecycle import _s
from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

if TYPE_CHECKING:
    from pallas.core.foundation.db.modules import ImageCache

_IMAGE_BLOB_LOCK_NAMESPACE = 0x50414C4C


def image_blob_lock_key(content_hash: str) -> int:
    """Return a process-stable PostgreSQL advisory-lock key for a content hash."""
    return int.from_bytes(hashlib.sha256(content_hash.encode("utf-8")).digest()[:4], "big", signed=True)


async def acquire_image_blob_lock(session, content_hash: str) -> None:
    """Acquire the shared transaction lock before reading references or touching a blob."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
        {"namespace": _IMAGE_BLOB_LOCK_NAMESPACE, "key": image_blob_lock_key(content_hash)},
    )


def image_cache_blob_snapshot(cache: ImageCache) -> tuple[bytes | None, str | None, str | None]:
    data = bytes(cache.blob_data) if cache.blob_data else None
    return data, _s(cache.content_hash), hashlib.sha256(data).hexdigest() if data else None


async def image_cache_legacy_alias_matches(session, cq_code: str, alias: str, data: bytes, actual_hash: str) -> bool:
    """Only trust a mismatched hash when the locked row still owns the same bytes."""
    row = (
        await session.execute(
            select(ImageCacheRow.content_hash, ImageCacheRow.blob_data, ImageCacheRow.blob_path)
            .where(ImageCacheRow.cq_code == cq_code)
            .with_for_update()
        )
    ).first()
    if row is None or row.content_hash != alias:
        return False
    stored_data = bytes(row.blob_data) if row.blob_data else None
    if stored_data is None:
        if not row.blob_path or canonical_image_blob_hash(row.blob_path) != actual_hash:
            return False
        stored_data = await asyncio.to_thread(read_image_blob_at, row.blob_path)
    if stored_data is None:
        return False
    return stored_data == data and hashlib.sha256(stored_data).hexdigest() == actual_hash


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


def image_cache_persist_blob(data: bytes | None, content_hash: str | None) -> dict[str, Any]:
    """在调用方持有 hash 锁时发布或复用内容匹配的 PG blob。"""
    if not data:
        return {}
    if not content_hash:
        raise ValueError("image blob content_hash is required")
    if hashlib.sha256(data).hexdigest() != content_hash:
        raise ValueError("image cache content_hash does not match blob_data")
    path = image_blob_abs_path(content_hash)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        blob_size = write_image_blob(content_hash, data)
    else:
        if not stat.S_ISREG(mode):
            raise ValueError("existing image blob is not a regular file")
        if path.read_bytes() != data:
            raise ValueError("existing image blob content does not match blob_data")
        blob_size = len(data)
    return {
        "blob_path": str(image_blob_rel_path(content_hash)),
        "blob_size": blob_size,
    }


async def _cleanup_image_cache_blobs(
    hashes: list[str | None], *, blob_paths: list[str | None] = (), session_factory=None
) -> list[tuple[str, int]]:
    present = {h for h in hashes if h}
    present.update(h for path in blob_paths if path and (h := canonical_image_blob_hash(path)))
    if not present:
        return []
    session_factory = session_factory or _repo.get_session
    removed = []
    for content_hash in present:
        async with session_factory() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            await acquire_image_blob_lock(session, content_hash)
            blob_path = str(image_blob_rel_path(content_hash))
            referenced = await session.scalar(
                select(ImageCacheRow.id)
                .where(
                    or_(
                        ImageCacheRow.content_hash == content_hash,
                        ImageCacheRow.blob_path == blob_path,
                    )
                )
                .limit(1)
            )
            if referenced is None:
                size = image_blob_size(content_hash)
                if delete_image_blob(content_hash):
                    removed.append((content_hash, size))
            await session.commit()
    return removed


async def image_cache_cleanup_blobs(hashes: list[str | None], *, blob_paths: list[str | None] = ()) -> None:
    await _cleanup_image_cache_blobs(hashes, blob_paths=blob_paths)


async def image_cache_cleanup_orphan_blobs(hashes: list[str], *, session_factory=None) -> list[tuple[str, int]]:
    return await _cleanup_image_cache_blobs(hashes, session_factory=session_factory)


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
        content_hash = _s(content_hash) or ""
        async with _repo.get_session() as session:
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            await acquire_image_blob_lock(session, content_hash)
            row = (
                await session.execute(
                    select(ImageCacheRow.id, ImageCacheRow.blob_data, ImageCacheRow.blob_path)
                    .where(ImageCacheRow.cq_code == cq_code)
                    .with_for_update()
                )
            ).first()
            if row is None:
                await session.commit()
                return
            data = bytes(row.blob_data) if row.blob_data else None
            if data is None and row.blob_path:
                data = await asyncio.to_thread(read_image_blob_at, row.blob_path)
            if not data or hashlib.sha256(data).hexdigest() != content_hash:
                raise ValueError("image cache content_hash does not match stored blob")
            await session.execute(
                update(ImageCacheRow).where(ImageCacheRow.id == row.id).values(content_hash=content_hash)
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
        data, requested_hash, actual_hash = image_cache_blob_snapshot(cache)
        if actual_hash and requested_hash and requested_hash != actual_hash:
            raise ValueError("image cache content_hash does not match blob_data")
        content_hash = actual_hash or requested_hash
        async with _repo.get_session() as session:
            if content_hash:
                await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
                await acquire_image_blob_lock(session, content_hash)
            blob = image_cache_persist_blob(data, content_hash)
            values: dict[str, Any] = {
                "cq_code": _s(cache.cq_code) or "",
                "content_hash": content_hash,
                "blob_path": blob.get("blob_path"),
                "blob_size": blob.get("blob_size"),
                "blob_data": None,
                "ref_times": cache.ref_times,
                "date": cache.date,
            }
            stmt = pg_insert(ImageCacheRow).values(values)
            await session.execute(stmt.on_conflict_do_nothing(index_elements=["cq_code"]))
            await session.commit()

    async def save(self, cache) -> None:
        """upsert 语义：存在则更新，否则插入。"""
        data, requested_hash, actual_hash = image_cache_blob_snapshot(cache)
        blob_hash = actual_hash or requested_hash
        stored_hash = requested_hash or actual_hash
        async with _repo.get_session() as session:
            if blob_hash:
                await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
                await acquire_image_blob_lock(session, blob_hash)
            if (
                data
                and requested_hash
                and actual_hash
                and requested_hash != actual_hash
                and not await image_cache_legacy_alias_matches(
                    session, _s(cache.cq_code) or "", requested_hash, data, actual_hash
                )
            ):
                raise ValueError("image cache content_hash does not match blob_data or trusted row")
            blob = image_cache_persist_blob(data, blob_hash)
            values: dict[str, Any] = {
                "cq_code": _s(cache.cq_code) or "",
                "content_hash": stored_hash,
                "blob_path": blob.get("blob_path"),
                "blob_size": blob.get("blob_size"),
                "blob_data": None,
                "ref_times": cache.ref_times,
                "date": cache.date,
            }
            stmt = pg_insert(ImageCacheRow).values(values)
            set_ = {
                "ref_times": stmt.excluded.ref_times,
                "date": stmt.excluded.date,
                "content_hash": stmt.excluded.content_hash,
                "blob_path": stmt.excluded.blob_path,
                "blob_size": stmt.excluded.blob_size,
                "blob_data": stmt.excluded.blob_data,
            }
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
            async with _repo.get_session() as session:
                rows = (
                    await session.execute(
                        select(ImageCacheRow.id)
                        .where(ImageCacheRow.date < int(before_date))
                        .limit(1000)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                if not rows:
                    break
                ids = [int(row[0]) for row in rows]
                result = await session.execute(
                    delete(ImageCacheRow)
                    .where(ImageCacheRow.id.in_(ids))
                    .returning(ImageCacheRow.content_hash, ImageCacheRow.blob_path)
                )
                deleted_rows = result.all()
                await session.commit()
            await image_cache_cleanup_blobs(
                [row[0] for row in deleted_rows], blob_paths=[row[1] for row in deleted_rows]
            )
            if len(deleted_rows) < 1000:
                break

    async def delete_low_ref(self, ref_threshold: int) -> None:
        while True:
            async with _repo.get_session() as session:
                rows = (
                    await session.execute(
                        select(ImageCacheRow.id)
                        .where(ImageCacheRow.ref_times < ref_threshold)
                        .limit(1000)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                if not rows:
                    break
                ids = [int(row[0]) for row in rows]
                result = await session.execute(
                    delete(ImageCacheRow)
                    .where(ImageCacheRow.id.in_(ids))
                    .returning(ImageCacheRow.content_hash, ImageCacheRow.blob_path)
                )
                deleted_rows = result.all()
                await session.commit()
            await image_cache_cleanup_blobs(
                [row[0] for row in deleted_rows], blob_paths=[row[1] for row in deleted_rows]
            )
            if len(deleted_rows) < 1000:
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

        async def delete_batch(where_clause, *, size_limit: int | None = None) -> tuple[int, int, int]:
            async with _repo.get_session() as session:
                stmt = (
                    select(ImageCacheRow.id, blob_size_expr)
                    .where(where_clause)
                    .order_by(
                        case((ImageCacheRow.ref_times <= 1, 0), else_=1),
                        ImageCacheRow.date,
                        ImageCacheRow.id,
                    )
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
                candidates = list((await session.execute(stmt)).all())
                if not candidates:
                    return 0, 0, 0
                rows = candidates
                if size_limit is not None:
                    selected = []
                    selected_bytes = 0
                    for row in rows:
                        selected.append(row)
                        selected_bytes += int(row[1])
                        if selected_bytes >= size_limit:
                            break
                    rows = selected
                ids = [int(row[0]) for row in rows]
                deleted = list(
                    (
                        await session.execute(
                            delete(ImageCacheRow)
                            .where(ImageCacheRow.id.in_(ids))
                            .returning(
                                ImageCacheRow.id,
                                ImageCacheRow.content_hash,
                                blob_size_expr,
                                ImageCacheRow.blob_path,
                            )
                        )
                    ).all()
                )
                await session.commit()
            await image_cache_cleanup_blobs([row[1] for row in deleted], blob_paths=[row[3] for row in deleted])
            return len(deleted), sum(int(row[2]) for row in deleted), len(candidates)

        expired = or_(
            ImageCacheRow.date < int(policy.absolute_before),
            and_(ImageCacheRow.date < int(policy.single_use_before), ImageCacheRow.ref_times <= 1),
        )
        while True:
            rows, blob_bytes, _candidate_count = await delete_batch(expired)
            deleted_rows += rows
            deleted_blob_bytes += blob_bytes
            if rows < batch_size:
                break

        remaining_blob_bytes = await total_blob_bytes()
        while remaining_blob_bytes > max_blob_bytes:
            required_bytes = remaining_blob_bytes - max_blob_bytes
            rows, blob_bytes, candidate_count = await delete_batch(
                literal_column("true"),
                size_limit=required_bytes,
            )
            if not rows:
                break
            deleted_rows += rows
            deleted_blob_bytes += blob_bytes
            # This is a fresh snapshot after the committed batch; concurrent writes may change it again.
            remaining_blob_bytes = await total_blob_bytes()
            if remaining_blob_bytes <= max_blob_bytes or blob_bytes >= required_bytes or candidate_count < batch_size:
                break

        remaining_blob_bytes = await total_blob_bytes()

        return ImageCachePruneResult(
            deleted_rows=deleted_rows,
            deleted_blob_bytes=deleted_blob_bytes,
            remaining_blob_bytes=remaining_blob_bytes,
        )
