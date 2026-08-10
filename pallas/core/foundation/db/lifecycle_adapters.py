"""Physical database discovery adapters for lifecycle management."""

from __future__ import annotations

import math
import time
from datetime import date, timedelta
from typing import Any, Protocol

from sqlalchemy import text

from .lifecycle_models import LifecycleObjectStat, LifecyclePolicy
from .lifecycle_registry import classify_object

POSTGRES_DISCOVERY_SQL = """
SELECT
    c.relname AS name,
    GREATEST(c.reltuples, 0)::bigint AS row_count,
    pg_total_relation_size(c.oid)::bigint AS size_bytes
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
ORDER BY c.relname
"""


class LifecycleAdapter(Protocol):
    backend: str

    async def discover_objects(self) -> list[LifecycleObjectStat]: ...

    async def preview_dataset(self, dataset_id: str, policy: LifecyclePolicy) -> tuple[int, int]: ...

    async def prune_dataset(self, dataset_id: str, policy: LifecyclePolicy) -> tuple[int, int]: ...


PG_DATASET_RULES = {
    "message_history": ("message", "id", "time", None),
    "repeater_context": ("context", "id", "time", None),
    "llm_chat": ("llm_chat_message", "id", "created_at", None),
    "background_jobs": ("background_job", "id", "finished_at", "status = 'done'"),
}


class PostgresLifecycleAdapter:
    backend = "postgresql"

    def __init__(self, *, session_factory: Any | None = None) -> None:
        if session_factory is None:
            from .repository_pg import get_session

            session_factory = get_session
        self.session_factory = session_factory

    async def discover_objects(self) -> list[LifecycleObjectStat]:
        async with self.session_factory(read_only=True) as session:
            result = await session.execute(text(POSTGRES_DISCOVERY_SQL))
            rows = result.mappings().all()
        return [object_stat(str(row["name"]), row.get("row_count"), row.get("size_bytes")) for row in rows]

    async def preview_dataset(self, dataset_id: str, policy: LifecyclePolicy) -> tuple[int, int]:
        if dataset_id == "image_cache":
            return await self.preview_image_cache(policy)
        if dataset_id == "llm_memory":
            return await self.preview_llm_memory()
        rule = PG_DATASET_RULES.get(dataset_id)
        if rule is None:
            raise ValueError(f"数据集不支持清理: {dataset_id}")
        table, _id_column, _time_column, _extra_filter = rule
        where, params = postgres_candidate_filter(dataset_id, policy)
        async with self.session_factory(read_only=True) as session:
            result = await session.execute(text(f"SELECT count(*) AS count FROM {table} WHERE {where}"), params)
            retention_count = int(result.mappings().all()[0]["count"])
        return await self.with_capacity_candidate(dataset_id, retention_count, policy)

    async def prune_dataset(self, dataset_id: str, policy: LifecyclePolicy) -> tuple[int, int]:
        if dataset_id == "image_cache":
            return await self.prune_image_cache(policy)
        if dataset_id == "llm_memory":
            return await self.prune_llm_memory()
        candidate_rows, candidate_bytes = await self.preview_dataset(dataset_id, policy)
        if candidate_rows <= 0:
            return 0, 0
        table, id_column, time_column, _extra_filter = PG_DATASET_RULES[dataset_id]
        where, filter_params = postgres_candidate_filter(dataset_id, policy)
        deleted = 0
        while deleted < candidate_rows:
            params = {**filter_params, "limit": min(1000, candidate_rows - deleted)}
            statement = text(
                f"DELETE FROM {table} WHERE {id_column} IN "
                f"(SELECT {id_column} FROM {table} WHERE {where} ORDER BY {time_column} ASC LIMIT :limit)"
            )
            async with self.session_factory() as session:
                result = await session.execute(statement, params)
                await session.commit()
                batch_deleted = int(result.rowcount or 0)
            deleted += batch_deleted
            if batch_deleted == 0:
                break
        return deleted, proportional_bytes(candidate_bytes, deleted, candidate_rows)

    async def with_capacity_candidate(
        self,
        dataset_id: str,
        retention_count: int,
        policy: LifecyclePolicy,
    ) -> tuple[int, int]:
        objects = [item for item in await self.discover_objects() if item.dataset_id == dataset_id]
        total_count = sum(item.row_count or 0 for item in objects)
        total_bytes = sum(item.size_bytes or 0 for item in objects)
        capacity_count = capacity_candidate_count(total_count, total_bytes, policy.max_bytes)
        candidate_count = min(total_count, max(retention_count, capacity_count))
        return candidate_count, proportional_bytes(total_bytes, candidate_count, total_count)

    async def preview_image_cache(self, policy: LifecyclePolicy) -> tuple[int, int]:
        async with self.session_factory(read_only=True) as session:
            result = await session.execute(
                text(
                    "SELECT date, ref_times, COALESCE(octet_length(blob_data), 0) AS bytes "
                    "FROM image_cache ORDER BY CASE WHEN ref_times <= 1 THEN 0 ELSE 1 END, date, id"
                )
            )
            rows = result.mappings().all()
        return preview_image_cache_rows(
            [(int(row["date"]), int(row["ref_times"]), int(row["bytes"])) for row in rows],
            policy,
        )

    async def prune_image_cache(self, policy: LifecyclePolicy) -> tuple[int, int]:
        from pallas.core.foundation.db import make_image_cache_repository

        result = await make_image_cache_repository().prune(image_cache_prune_policy(policy))
        return result.deleted_rows, result.deleted_blob_bytes

    async def preview_llm_memory(self) -> tuple[int, int]:
        now = int(time.time())
        async with self.session_factory(read_only=True) as session:
            result = await session.execute(
                text("SELECT count(*) AS count FROM llm_memory_entry WHERE expires_at > 0 AND expires_at < :now"),
                {"now": now},
            )
            count = int(result.mappings().all()[0]["count"])
        return await self.with_capacity_candidate("llm_memory", count, LifecyclePolicy(True, None, None))

    async def prune_llm_memory(self) -> tuple[int, int]:
        before = await self.preview_llm_memory()
        async with self.session_factory() as session:
            result = await session.execute(
                text("DELETE FROM llm_memory_entry WHERE expires_at > 0 AND expires_at < :now"),
                {"now": int(time.time())},
            )
            await session.commit()
            deleted = int(result.rowcount or 0)
        return deleted, proportional_bytes(before[1], deleted, before[0])


class MongoLifecycleAdapter:
    backend = "mongodb"

    def __init__(self, *, database: Any | None = None) -> None:
        self.database = database

    def get_database(self) -> Any:
        if self.database is not None:
            return self.database
        from .modules import Message

        return Message.get_pymongo_collection().database

    async def discover_objects(self) -> list[LifecycleObjectStat]:
        database = self.get_database()
        names = sorted(name for name in await database.list_collection_names() if not name.startswith("system."))
        objects: list[LifecycleObjectStat] = []
        for name in names:
            try:
                stats = await database.command("collStats", name)
                objects.append(object_stat(name, stats.get("count"), stats.get("storageSize")))
            except Exception as exc:  # noqa: BLE001
                objects.append(object_stat(name, None, None, error=str(exc)))
        return objects

    async def preview_dataset(self, dataset_id: str, policy: LifecyclePolicy) -> tuple[int, int]:
        database = self.get_database()
        if dataset_id == "image_cache":
            return await self.preview_image_cache(policy)
        collection_name, time_column, extra_filter = mongo_rule(dataset_id)
        query = dict(extra_filter)
        if dataset_id == "llm_memory":
            query = {"expires_at": {"$gt": 0, "$lt": int(time.time())}}
            retention_count = int(await database[collection_name].count_documents(query))
            objects = [item for item in await self.discover_objects() if item.dataset_id == dataset_id]
            total_count = sum(item.row_count or 0 for item in objects)
            total_bytes = sum(item.size_bytes or 0 for item in objects)
            return retention_count, proportional_bytes(total_bytes, retention_count, total_count)
        cutoff = retention_cutoff(policy)
        if cutoff is not None:
            query[time_column] = {"$lt": cutoff}
        collection = database[collection_name]
        retention_count = int(await collection.count_documents(query))
        objects = [item for item in await self.discover_objects() if item.dataset_id == dataset_id]
        total_count = sum(item.row_count or 0 for item in objects)
        total_bytes = sum(item.size_bytes or 0 for item in objects)
        capacity_count = capacity_candidate_count(total_count, total_bytes, policy.max_bytes)
        candidate_count = min(total_count, max(retention_count, capacity_count))
        return candidate_count, proportional_bytes(total_bytes, candidate_count, total_count)

    async def prune_dataset(self, dataset_id: str, policy: LifecyclePolicy) -> tuple[int, int]:
        database = self.get_database()
        if dataset_id == "image_cache":
            return await self.prune_image_cache(policy)
        if dataset_id == "llm_memory":
            now = int(time.time())
            result = await database["llm_memory_entry"].delete_many({"expires_at": {"$gt": 0, "$lt": now}})
            return int(result.deleted_count), 0
        candidate_count, candidate_bytes = await self.preview_dataset(dataset_id, policy)
        if candidate_count <= 0:
            return 0, 0
        collection_name, time_column, extra_filter = mongo_rule(dataset_id)
        collection = database[collection_name]
        deleted = 0
        while deleted < candidate_count:
            limit = min(1000, candidate_count - deleted)
            cursor = collection.find(dict(extra_filter), {"_id": 1}).sort(time_column, 1).limit(limit)
            ids = [row["_id"] async for row in cursor]
            if not ids:
                break
            result = await collection.delete_many({"_id": {"$in": ids}})
            batch_deleted = int(result.deleted_count)
            deleted += batch_deleted
            if batch_deleted == 0:
                break
        return deleted, proportional_bytes(candidate_bytes, deleted, candidate_count)

    async def preview_image_cache(self, policy: LifecyclePolicy) -> tuple[int, int]:
        collection = self.get_database()["image_cache"]
        cursor = collection.find({}, {"date": 1, "ref_times": 1, "blob_data": 1}).sort([
            ("ref_times", 1),
            ("date", 1),
            ("_id", 1),
        ])
        rows = [
            (int(row.get("date") or 0), int(row.get("ref_times") or 0), len(row.get("blob_data") or b""))
            async for row in cursor
        ]
        return preview_image_cache_rows(rows, policy)

    async def prune_image_cache(self, policy: LifecyclePolicy) -> tuple[int, int]:
        from pallas.core.foundation.db import make_image_cache_repository

        result = await make_image_cache_repository().prune(image_cache_prune_policy(policy))
        return result.deleted_rows, result.deleted_blob_bytes


def object_stat(
    name: str,
    row_count: object,
    size_bytes: object,
    *,
    error: str | None = None,
) -> LifecycleObjectStat:
    classification = classify_object(name)
    return LifecycleObjectStat(
        name=name,
        row_count=int(row_count) if row_count is not None else None,
        size_bytes=int(size_bytes) if size_bytes is not None else None,
        dataset_id=classification.dataset_id,
        protected=classification.protected,
        protection_reason=classification.protection_reason,
        error=error,
    )


def make_lifecycle_adapter(backend: str | None = None) -> LifecycleAdapter:
    if backend is None:
        from .runtime import get_db_backend

        backend = get_db_backend()
    normalized = str(backend).strip().lower()
    if normalized in {"postgres", "postgresql", "pg"}:
        return PostgresLifecycleAdapter()
    if normalized in {"mongo", "mongodb"}:
        return MongoLifecycleAdapter()
    raise ValueError(f"不支持的数据库后端: {backend}")


def retention_cutoff(policy: LifecyclePolicy) -> int | None:
    if policy.retention_days is None:
        return None
    return int(time.time()) - policy.retention_days * 86400


def postgres_candidate_filter(dataset_id: str, policy: LifecyclePolicy) -> tuple[str, dict[str, object]]:
    _table, _id_column, time_column, extra_filter = PG_DATASET_RULES[dataset_id]
    clauses = [f"{time_column} IS NOT NULL"]
    params: dict[str, object] = {}
    cutoff = retention_cutoff(policy)
    if cutoff is not None:
        clauses.append(f"{time_column} < :cutoff")
        params["cutoff"] = cutoff
    if extra_filter:
        clauses.append(extra_filter)
    return " AND ".join(clauses), params


def image_cache_cutoff(policy: LifecyclePolicy) -> int:
    return int((date.today() - timedelta(days=policy.retention_days or 90)).strftime("%Y%m%d"))


def image_cache_prune_policy(policy: LifecyclePolicy):
    from pallas.core.foundation.db.repository import ImageCachePrunePolicy

    current = date.today()
    absolute_days = policy.retention_days or 90
    return ImageCachePrunePolicy(
        single_use_before=int((current - timedelta(days=min(30, absolute_days))).strftime("%Y%m%d")),
        absolute_before=int((current - timedelta(days=absolute_days)).strftime("%Y%m%d")),
        max_blob_bytes=policy.max_bytes or 20 * 1024**3,
        batch_size=1000,
    )


def preview_image_cache_rows(rows: list[tuple[int, int, int]], policy: LifecyclePolicy) -> tuple[int, int]:
    prune_policy = image_cache_prune_policy(policy)
    deleted: list[tuple[int, int, int]] = []
    remaining: list[tuple[int, int, int]] = []
    for row in rows:
        if row[0] < prune_policy.absolute_before or (row[0] < prune_policy.single_use_before and row[1] <= 1):
            deleted.append(row)
        else:
            remaining.append(row)
    remaining_bytes = sum(row[2] for row in remaining)
    while remaining_bytes > prune_policy.max_blob_bytes:
        batch = remaining[: prune_policy.batch_size]
        selected: list[tuple[int, int, int]] = []
        selected_bytes = 0
        for row in batch:
            selected.append(row)
            selected_bytes += row[2]
            if selected_bytes >= remaining_bytes - prune_policy.max_blob_bytes:
                break
        if not selected:
            break
        deleted.extend(selected)
        remaining = remaining[len(selected) :]
        remaining_bytes -= selected_bytes
    return len(deleted), sum(row[2] for row in deleted)


def capacity_candidate_count(total_count: int, total_bytes: int, max_bytes: int | None) -> int:
    if max_bytes is None or total_bytes <= max_bytes or total_count <= 0:
        return 0
    return min(total_count, math.ceil(total_count * (total_bytes - max_bytes) / total_bytes))


def proportional_bytes(total_bytes: int, candidate_count: int, total_count: int) -> int:
    if total_bytes <= 0 or candidate_count <= 0 or total_count <= 0:
        return 0
    return min(total_bytes, math.ceil(total_bytes * candidate_count / total_count))


def mongo_rule(dataset_id: str) -> tuple[str, str, dict[str, object]]:
    rules: dict[str, tuple[str, str, dict[str, object]]] = {
        "message_history": ("message", "time", {}),
        "repeater_context": ("context", "time", {}),
        "image_cache": ("image_cache", "date", {}),
        "llm_chat": ("llm_chat_message", "created_at", {}),
        "background_jobs": ("background_jobs", "finished_at", {"status": "done"}),
        "llm_memory": ("llm_memory_entry", "expires_at", {"expires_at": {"$gt": 0}}),
    }
    try:
        return rules[dataset_id]
    except KeyError:
        raise ValueError(f"数据集不支持清理: {dataset_id}") from None
