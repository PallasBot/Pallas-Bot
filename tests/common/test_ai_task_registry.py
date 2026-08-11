from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.core.foundation.config import TaskManager
from pallas.core.platform.shard.coord import ai_task_registry as mod


@pytest.fixture(autouse=True)
def clear_redis_caches():
    from pallas.core.platform.coord import redis_claim as rc
    from pallas.core.platform.coord import redis_settings as rs

    rs.clear_coord_redis_settings_cache()
    rc.clear_coord_redis_client_cache()
    yield
    rs.clear_coord_redis_settings_cache()
    rc.clear_coord_redis_client_cache()


def test_ai_task_registry_survives_long_queue_delay(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(mod, "current_worker_port", lambda: 7973)
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: SimpleNamespace(shard_id=3))
    monkeypatch.setattr(mod, "get_shard_registry", lambda: SimpleNamespace(shard_for_bot=lambda _bot_id: None))

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
    monkeypatch.setattr("pallas.core.foundation.config.time.time", lambda: start + 601.0)
    monkeypatch.setattr("pallas.core.platform.shard.coord.ai_task_registry.ai_task_ttl_sec", lambda: 86400.0)

    await TaskManager.refresh()

    assert "task-1" in TaskManager._tasks


async def test_task_manager_claim_task_is_one_shot(monkeypatch) -> None:
    import time

    start = time.time()
    TaskManager._tasks = {
        "task-claim": {
            "bot_id": "123456",
            "group_id": 42,
            "start_time": start,
        }
    }
    monkeypatch.setattr("pallas.core.platform.shard.coord.ai_task_registry.ai_task_ttl_sec", lambda: 86400.0)
    monkeypatch.setattr(
        "pallas.core.platform.shard.coord.ai_task_registry.remove_ai_task",
        lambda _task_id: None,
    )

    async def inline_to_thread(function, *args):
        return function(*args)

    monkeypatch.setattr("pallas.core.foundation.config.asyncio.to_thread", inline_to_thread)

    first = await TaskManager.claim_task("task-claim")
    second = await TaskManager.claim_task("task-claim")

    assert first is not None
    assert first["group_id"] == 42
    assert second is None
    assert "task-claim" not in TaskManager._tasks


def test_ai_task_registry_uses_redis(fake_coord_redis, monkeypatch) -> None:
    now = 1000.0
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(mod, "current_worker_port", lambda: 7973)
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: SimpleNamespace(shard_id=3))
    monkeypatch.setattr(mod, "get_shard_registry", lambda: SimpleNamespace(shard_for_bot=lambda _bot_id: None))
    monkeypatch.setattr(mod.time, "time", lambda: now)

    mod.register_ai_task(
        "task-redis",
        {"bot_id": "123456", "group_id": 42, "start_time": now},
    )

    rec = mod.get_ai_task_record("task-redis")
    assert rec is not None
    assert rec["worker_port"] == 7973
    assert mod.ai_task_redis_key("task-redis") in fake_coord_redis[0]

    mod.remove_ai_task("task-redis")
    assert mod.get_ai_task_record("task-redis") is None


def test_ai_task_registry_persists_unified_runtime_callback_without_worker_route(fake_coord_redis, monkeypatch) -> None:
    now = 1250.0
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(mod.time, "time", lambda: now)

    mod.register_ai_task(
        "task-unified",
        {
            "bot_id": "123456",
            "group_id": 42,
            "user_id": 7,
            "task_type": "sing",
            "start_time": now,
        },
    )

    rec = mod.get_ai_task_record("task-unified")
    assert rec is not None
    assert rec["bot_id"] == "123456"
    assert rec["group_id"] == 42
    assert rec["task_type"] == "sing"
    assert "shard_id" not in rec
    assert "worker_port" not in rec

    claimed = mod.claim_ai_task_record("task-unified")
    assert claimed == rec
    assert mod.claim_ai_task_record("task-unified") is None


def test_ai_task_registry_preserves_json_callback_context(fake_coord_redis, monkeypatch) -> None:
    now = 1300.0
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(mod.time, "time", lambda: now)
    callback_context = {
        "user_text": "再来一杯",
        "fallback_text": "语料原文",
        "candidate_pool": ["第一条", "第二条"],
        "llm_route": "repeater_polish",
        "behavior_scene": "drunk_chat",
        "last_reply_text": "上一条回复",
        "recent_reply_texts": ["较早回复", "上一条回复"],
        "want_tts": True,
    }

    mod.register_ai_task(
        "task-context",
        {
            "bot_id": "123456",
            "group_id": 42,
            "user_id": 7,
            "task_type": "chat_drunk",
            "start_time": now,
            **callback_context,
        },
    )

    rec = mod.get_ai_task_record("task-context")
    assert rec is not None
    assert {key: rec[key] for key in callback_context} == callback_context


def test_ai_task_registry_skips_non_json_task_context_without_raising(monkeypatch) -> None:
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: False)
    writes: list[dict] = []
    monkeypatch.setattr(mod, "write_ai_task_redis_sync", lambda rec, **_kwargs: writes.append(rec))

    mod.register_ai_task("task-object", {"bot_id": "123456", "opaque": object()})

    assert writes == []


def test_claim_ai_task_record_is_one_shot(fake_coord_redis, monkeypatch) -> None:
    now = 1500.0
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(mod, "current_worker_port", lambda: 7973)
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: SimpleNamespace(shard_id=3))
    monkeypatch.setattr(mod, "get_shard_registry", lambda: SimpleNamespace(shard_for_bot=lambda _bot_id: None))
    monkeypatch.setattr(mod.time, "time", lambda: now)

    mod.register_ai_task(
        "task-claim-redis",
        {"bot_id": "123456", "group_id": 42, "start_time": now},
    )

    first = mod.claim_ai_task_record("task-claim-redis")
    second = mod.claim_ai_task_record("task-claim-redis")

    assert first is not None
    assert first["worker_port"] == 7973
    assert second is None
    assert mod.get_ai_task_record("task-claim-redis") is None


def test_ai_task_registry_requires_redis_when_sharding(monkeypatch) -> None:
    now = 2000.0
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(mod, "current_worker_port", lambda: 7974)
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: SimpleNamespace(shard_id=4))
    monkeypatch.setattr(mod.time, "time", lambda: now)
    monkeypatch.setattr("pallas.core.platform.coord.redis_settings.coord_redis_enabled", lambda: False)

    mod.register_ai_task(
        "task-none",
        {"bot_id": "654321", "group_id": 99, "start_time": now},
    )

    assert mod.get_ai_task_record("task-none") is None


def test_ai_task_registry_routes_by_bot_shard_even_when_registered_on_other_worker(
    fake_coord_redis, monkeypatch
) -> None:
    now = 3000.0
    monkeypatch.setattr(mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(mod, "current_worker_port", lambda: 7976)
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: SimpleNamespace(shard_id=6))
    monkeypatch.setattr(mod.time, "time", lambda: now)

    class FakeRegistry:
        def shard_for_bot(self, bot_id: str) -> int | None:
            return 3 if str(bot_id) == "3234802804" else None

    monkeypatch.setattr(mod, "get_shard_registry", lambda: FakeRegistry())
    monkeypatch.setattr(mod, "worker_port_for_shard", lambda sid, registry=None: 7973 if int(sid) == 3 else 0)

    mod.register_ai_task(
        "task-cross-worker",
        {"bot_id": "3234802804", "group_id": 626266902, "start_time": now, "task_type": "sing"},
    )

    rec = mod.get_ai_task_record("task-cross-worker")
    assert rec is not None
    assert rec["bot_id"] == "3234802804"
    assert rec["shard_id"] == 3
    assert rec["worker_port"] == 7973
