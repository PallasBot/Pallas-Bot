from __future__ import annotations

import pytest

from src.platform.shard.coord import maa_pending_registry as mod
from src.plugins.maa.store import NotifyTarget, PendingTask, pending_task_to_dict


@pytest.mark.asyncio
async def test_shard_pending_enqueue_and_list(fake_coord_redis) -> None:
    task = PendingTask(
        task_id="01TASK",
        user="3023094357",
        device="c27e4912dfa147d8a7c1d9a6d658b06d",
        task_type="CaptureImageNow",
        params=None,
        notify=NotifyTarget(bot_id=923722427, user_id=3023094357, group_id=None),
    )
    mod.enqueue_task_sync(pending_task_to_dict(task))

    listed = mod.list_pending_sync("3023094357", task.device)
    assert len(listed) == 1
    assert listed[0]["task_type"] == "CaptureImageNow"

    marked = mod.mark_reported_sync("01TASK")
    assert marked is not None
    assert mod.list_pending_sync("3023094357", task.device) == []


@pytest.mark.asyncio
async def test_store_pending_count_uses_shard_redis(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.platform.shard.context.is_sharding_active",
        lambda: True,
    )

    from src.plugins.maa.store import MaaStore

    store = MaaStore()
    task = PendingTask(
        task_id="02TASK",
        user="3023094357",
        device="c27e4912dfa147d8a7c1d9a6d658b06d",
        task_type="StopTask",
        params=None,
        notify=NotifyTarget(bot_id=923722427, user_id=3023094357),
    )
    mod.enqueue_task_sync(pending_task_to_dict(task))
    assert await store.pending_count_for_user(3023094357) == 1
    raw = await store.pending_tasks_for("3023094357", task.device)
    assert len(raw) == 1
    assert raw[0]["type"] == "StopTask"
