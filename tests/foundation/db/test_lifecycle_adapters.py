from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from pallas.core.foundation.db.lifecycle_adapters import (
    MongoLifecycleAdapter,
    PostgresLifecycleAdapter,
    capacity_candidate_count,
    image_cache_prune_policy,
    preview_image_cache_rows,
    proportional_bytes,
)
from pallas.core.foundation.db.lifecycle_models import LifecyclePolicy


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows


class FakeSession:
    async def execute(self, _query: object) -> FakeResult:
        return FakeResult([
            {"name": "image_cache", "row_count": 69, "size_bytes": 40_386_400},
            {"name": "plugin_owned_table", "row_count": 3, "size_bytes": 8192},
        ])


@asynccontextmanager
async def fake_session_factory(*, read_only: bool = False) -> AsyncIterator[FakeSession]:
    assert read_only is True
    yield FakeSession()


@pytest.mark.asyncio
async def test_postgres_discovers_registered_and_unknown_tables() -> None:
    objects = await PostgresLifecycleAdapter(session_factory=fake_session_factory).discover_objects()

    assert [(item.name, item.row_count, item.size_bytes) for item in objects] == [
        ("image_cache", 69, 40_386_400),
        ("plugin_owned_table", 3, 8192),
    ]
    assert objects[0].dataset_id == "image_cache"
    assert objects[0].protected is False
    assert objects[1].dataset_id is None
    assert objects[1].protected is True


class FakeMongoDatabase:
    async def list_collection_names(self) -> list[str]:
        return ["message", "system.profile", "plugin_events"]

    async def command(self, command: str, name: str) -> dict[str, Any]:
        assert command == "collStats"
        if name == "plugin_events":
            raise RuntimeError("stats unavailable")
        return {"count": 12, "storageSize": 4096}


@pytest.mark.asyncio
async def test_mongo_keeps_collection_when_stats_fail() -> None:
    objects = await MongoLifecycleAdapter(database=FakeMongoDatabase()).discover_objects()

    assert [item.name for item in objects] == ["message", "plugin_events"]
    assert objects[0].dataset_id == "message_history"
    assert objects[0].row_count == 12
    assert objects[1].protected is True
    assert objects[1].error == "stats unavailable"


def test_capacity_candidate_uses_the_oldest_proportional_rows() -> None:
    assert capacity_candidate_count(100, 1000, 800) == 20
    assert capacity_candidate_count(100, 1000, 1000) == 0
    assert proportional_bytes(1000, 20, 100) == 200


def test_image_cache_preview_matches_single_use_expiry_and_capacity_pruning() -> None:
    policy = LifecyclePolicy(True, 30, 100)
    prune_policy = image_cache_prune_policy(policy)

    rows = [
        (prune_policy.absolute_before - 1, 8, 10),
        (prune_policy.single_use_before - 1, 1, 20),
        (prune_policy.single_use_before + 1, 1, 60),
        (prune_policy.single_use_before + 1, 8, 70),
    ]

    assert preview_image_cache_rows(rows, policy) == (3, 90)


@pytest.mark.asyncio
async def test_mongo_memory_preview_never_matches_non_expiring_entries() -> None:
    seen_queries: list[dict[str, Any]] = []

    class MemoryCollection:
        async def count_documents(self, query: dict[str, Any]) -> int:
            seen_queries.append(query)
            return 2

    class MemoryDatabase(FakeMongoDatabase):
        def __getitem__(self, name: str) -> MemoryCollection:
            assert name == "llm_memory_entry"
            return MemoryCollection()

        async def list_collection_names(self) -> list[str]:
            return ["llm_memory_entry"]

    await MongoLifecycleAdapter(database=MemoryDatabase()).preview_dataset(
        "llm_memory",
        LifecyclePolicy(True, 30, 1024**3),
    )

    assert seen_queries[0]["expires_at"]["$gt"] == 0


@pytest.mark.asyncio
async def test_postgres_background_job_prune_keeps_pending_rows_outside_candidate_filter() -> None:
    statements: list[str] = []

    class DeleteResult:
        rowcount = 1

    class DeleteSession:
        async def execute(self, statement: object, _params: dict[str, object]) -> DeleteResult:
            statements.append(str(statement))
            return DeleteResult()

        async def commit(self) -> None:
            return None

    @asynccontextmanager
    async def delete_session_factory() -> AsyncIterator[DeleteSession]:
        yield DeleteSession()

    adapter = PostgresLifecycleAdapter(session_factory=delete_session_factory)

    async def one_candidate(_dataset_id: str, _policy: LifecyclePolicy) -> tuple[int, int]:
        return 1, 1

    adapter.preview_dataset = one_candidate  # type: ignore[method-assign]
    await adapter.prune_dataset("background_jobs", LifecyclePolicy(True, 30, None))

    assert "finished_at IS NOT NULL" in statements[0]
    assert "finished_at < :cutoff" in statements[0]
    assert "status = 'done'" in statements[0]
