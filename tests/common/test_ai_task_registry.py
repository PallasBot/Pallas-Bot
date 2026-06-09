from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.foundation.config import TaskManager
from src.platform.shard.coord import ai_task_registry as mod
from src.platform.shard.coord import ai_task_registry_redis as redis_mod


@pytest.fixture(autouse=True)
def clear_redis_caches():
    from src.platform.coord import redis_claim as rc
    from src.platform.coord import redis_settings as rs

    rs.clear_coord_redis_settings_cache()
    rc.clear_coord_redis_client_cache()
    yield
    rs.clear_coord_redis_settings_cache()
    rc.clear_coord_redis_client_cache()


def test_ai_task_registry_survives_long_queue_delay(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(mod, "current_worker_port", lambda: 7973)
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: SimpleNamespace(shard_id=3))

    start = 1000.0
    monkeypatch.setattr(mod.time, "time", lambda: start)
    mod.register_ai_task(
        "task-1",
        {
            "bot_id": "123456",
            "group_id": 42,
            "start_time": start,
        },
    )

    monkeypatch.setattr(mod.time, "time", lambda: start + 601.0)
    rec = mod.get_ai_task_record("task-1")

    assert rec is not None
    assert rec["worker_port"] == 7973


async def test_task_manager_keeps_ai_task_beyond_legacy_10min(monkeypatch) -> None:
    start = 1000.0
    TaskManager._tasks = {
        "task-1": {
            "bot_id": "123456",
            "group_id": 42,
            "start_time": start,
        }
    }
    monkeypatch.setattr("src.foundation.config.time.time", lambda: start + 601.0)
    monkeypatch.setattr("src.platform.shard.coord.ai_task_registry.ai_task_ttl_sec", lambda: 86400.0)

    await TaskManager.refresh()

    assert "task-1" in TaskManager._tasks


def test_ai_task_registry_uses_redis(fake_coord_redis, monkeypatch) -> None:
    now = 1000.0
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(mod, "current_worker_port", lambda: 7973)
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: SimpleNamespace(shard_id=3))
    monkeypatch.setattr(mod.time, "time", lambda: now)

    mod.register_ai_task(
        "task-redis",
        {"bot_id": "123456", "group_id": 42, "start_time": now},
    )

    rec = mod.get_ai_task_record("task-redis")
    assert rec is not None
    assert rec["worker_port"] == 7973
    assert redis_mod.ai_task_redis_key("task-redis") in fake_coord_redis[0]

    mod.remove_ai_task("task-redis")
    assert mod.get_ai_task_record("task-redis") is None


def test_ai_task_registry_requires_redis_when_sharding(monkeypatch) -> None:
    now = 2000.0
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(mod, "current_worker_port", lambda: 7974)
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: SimpleNamespace(shard_id=4))
    monkeypatch.setattr(mod.time, "time", lambda: now)
    monkeypatch.setattr("src.platform.coord.redis_settings.coord_redis_enabled", lambda: False)

    mod.register_ai_task(
        "task-none",
        {"bot_id": "654321", "group_id": 99, "start_time": now},
    )

    assert mod.get_ai_task_record("task-none") is None
