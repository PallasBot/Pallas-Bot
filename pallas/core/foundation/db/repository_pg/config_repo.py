"""PostgreSQL Bot/Group/User 配置 Repository（TTL 缓存）"""

from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from pallas.core.foundation.db import repository_pg as _repo
from pallas.core.foundation.db.repository_pg.lifecycle import _CONFIG_CACHES, _strip_null_deep
from pallas.core.foundation.db.repository_pg.schema import (
    BotConfigRow,
    GroupConfigRow,
    UserConfigRow,
)

_CONFIG_TABLE_MAP: dict[str, tuple[type, str]] = {
    "bot_config": (BotConfigRow, "account"),
    "group_config": (GroupConfigRow, "group_id"),
    "user_config": (UserConfigRow, "user_id"),
}


def _cfg_env(key: str, default: str) -> str:
    try:
        import nonebot

        val = getattr(nonebot.get_driver().config, key.lower(), None)
        if val is not None:
            return str(val)
    except Exception:
        pass
    return os.getenv(key, default)


class _ConfigCache:
    """
    简单的容量 + TTL 缓存，对齐 Mongo Beanie 的 model-level cache 语义。
    对每个 (row_class) 一个实例；key 是主键值，value 是 (row, expire_ts)
    None 也会被缓存。
    """

    def __init__(self, ttl: float, capacity: int) -> None:
        self._ttl = ttl
        self._capacity = capacity
        self._store: OrderedDict[Any, tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: Any) -> tuple[bool, Any]:
        """TTL 缓存查询，返回 hit 与 value。"""
        if self._ttl <= 0 or self._capacity <= 0:
            return False, None
        async with self._lock:
            item = self._store.get(key)
            if item is None:
                return False, None
            value, expire_ts = item
            if expire_ts <= time.time():
                self._store.pop(key, None)
                return False, None
            self._store.move_to_end(key)
            return True, value

    async def put(self, key: Any, value: Any) -> None:
        if self._ttl <= 0 or self._capacity <= 0:
            return
        async with self._lock:
            self._store[key] = (value, time.time() + self._ttl)
            self._store.move_to_end(key)
            while len(self._store) > self._capacity:
                self._store.popitem(last=False)

    async def invalidate(self, key: Any) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()


def _get_config_cache(row_class: type) -> _ConfigCache:
    cache = _CONFIG_CACHES.get(row_class)
    if cache is None:
        ttl = float(_cfg_env("PG_CONFIG_CACHE_TTL", "60"))
        capacity = int(_cfg_env("PG_CONFIG_CACHE_SIZE", "10000"))
        cache = _ConfigCache(ttl=ttl, capacity=capacity)
        _CONFIG_CACHES[row_class] = cache
    return cache


class PgConfigRepository:
    def __init__(self, table: str, primary_key: str) -> None:
        if table not in _CONFIG_TABLE_MAP:
            raise ValueError(f"Unknown config table: {table}")
        row_class, pk_field = _CONFIG_TABLE_MAP[table]
        # primary_key 由工厂函数传入，
        # 这里做一致性断言，避免静默与 _CONFIG_TABLE_MAP 失同步。
        if primary_key != pk_field:
            raise ValueError(f"primary_key {primary_key!r} 与 {table} 登记的主键 {pk_field!r} 不一致")
        self._row_class, self._pk_field = row_class, pk_field
        self._cache = _get_config_cache(self._row_class)

    async def get(self, key_id: int, *, ignore_cache: bool = False) -> Any | None:
        if not ignore_cache:
            hit, value = await self._cache.get(key_id)
            if hit:
                return value
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(
                select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                session.expunge(row)
        await self._cache.put(key_id, row)
        return row

    async def list_all(self) -> list[Any]:
        async with _repo.get_session(read_only=True) as session:
            rows = list((await session.execute(select(self._row_class))).scalars().all())
            for row in rows:
                session.expunge(row)
        return rows

    async def get_or_create(self, key_id: int, **defaults: Any) -> tuple[Any, bool]:
        async with _repo.get_session() as session:
            result = await session.execute(
                select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                session.expunge(row)
                await self._cache.put(key_id, row)
                return row, False
            try:
                new_row = self._row_class(**{self._pk_field: key_id, **_strip_null_deep(defaults)})
                session.add(new_row)
                await session.commit()
            except IntegrityError:
                # 并发下已被其他 writer 插入，回源拿最新行
                await session.rollback()
                result = await session.execute(
                    select(self._row_class).where(getattr(self._row_class, self._pk_field) == key_id)
                )
                existing = result.scalar_one_or_none()
                if existing is not None:
                    session.expunge(existing)
                await self._cache.put(key_id, existing)
                return existing, False
            session.expunge(new_row)
            await self._cache.put(key_id, new_row)
            return new_row, True

    async def upsert_field(self, key_id: int, field: str, value: Any) -> None:
        """字段级 upsert，基于主键 ON CONFLICT 原子化。"""
        cleaned_value = _strip_null_deep(value)
        async with _repo.get_session() as session:
            stmt = pg_insert(self._row_class).values(**{self._pk_field: key_id, field: cleaned_value})
            stmt = stmt.on_conflict_do_update(
                index_elements=[self._pk_field],
                set_={field: getattr(stmt.excluded, field)},
            )
            await session.execute(stmt)
            await session.commit()
        await self._cache.invalidate(key_id)

    async def upsert_fields(self, key_id: int, fields: dict[str, Any]) -> None:
        """批量字段级 upsert"""
        if not fields:
            return
        cleaned = {k: _strip_null_deep(v) for k, v in fields.items()}
        async with _repo.get_session() as session:
            stmt = pg_insert(self._row_class).values(**{self._pk_field: key_id, **cleaned})
            stmt = stmt.on_conflict_do_update(
                index_elements=[self._pk_field],
                set_={k: getattr(stmt.excluded, k) for k in cleaned},
            )
            await session.execute(stmt)
            await session.commit()
        await self._cache.invalidate(key_id)

    async def invalidate_cache(self) -> None:
        await self._cache.clear()
