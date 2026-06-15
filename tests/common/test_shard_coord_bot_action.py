from __future__ import annotations

import asyncio
import time

import pytest

from src.platform.shard.coord import bot_action as mod


def test_bot_action_request_roundtrip(fake_coord_redis) -> None:
    request_id = mod._publish_request(
        action="set_group_card",
        bot_qq=300,
        payload={"group_id": 1, "user_id": 2, "card": "test"},
        timeout_sec=5.0,
    )
    mod._finish_request(request_id, ok=True, result=None)

    async def run() -> None:
        ok, result = await mod._wait_request(request_id, deadline=time.time() + 2.0)
        assert ok is True
        assert result is None

    asyncio.run(run())


@pytest.mark.asyncio
async def test_execute_local_repeater_fanout_reply_schedules_background_task(monkeypatch):
    scheduled: list[str | None] = []

    def fake_create_task(coro, *, name=None):
        scheduled.append(name)
        coro.close()

        class _DummyTask:
            pass

        return _DummyTask()

    async def fake_run_repeater_reply_for_bot(_bot_id: int, _payload: dict[str, object]) -> None:
        await asyncio.sleep(3600)

    from src.plugins.repeater import fanout_reply as fanout_mod

    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr("nonebot.get_bots", lambda: {"300": object()})
    monkeypatch.setattr(fanout_mod, "run_repeater_reply_for_bot", fake_run_repeater_reply_for_bot)

    ok, result = await asyncio.wait_for(
        mod._execute_local("repeater_fanout_reply", 300, {"group_id": 1}),
        timeout=0.05,
    )

    assert ok is True
    assert result is None
    assert scheduled == ["repeater_fanout_reply_300"]


@pytest.mark.asyncio
async def test_bot_action_listener_reads_messages_via_to_thread(monkeypatch):
    seen: list[str] = []

    class _PubSub:
        def subscribe(self, _channel: str) -> None:
            return None

        def get_message(self, *, timeout: float):
            seen.append(f"get:{timeout}")
            return {"type": "message", "data": '{"request_id":"req-1"}'}

        def unsubscribe(self, _channel: str) -> None:
            return None

        def close(self) -> None:
            return None

    class _Client:
        def pubsub(self, *, ignore_subscribe_messages: bool):
            return _PubSub()

    async def fake_to_thread(fn, *args, **kwargs):
        seen.append("to_thread")
        return fn(*args, **kwargs)

    async def fake_run_pending(request_id: str, local_ids: frozenset[str]) -> None:
        seen.append(f"run:{request_id}:{sorted(local_ids)}")
        raise asyncio.CancelledError

    monkeypatch.setattr("nonebot.get_bots", lambda: {"300": object()})
    monkeypatch.setattr(mod.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr("src.platform.coord.redis_settings.coord_redis_enabled", lambda: True)
    monkeypatch.setattr("src.platform.coord.redis_claim.get_coord_redis_client", lambda: _Client())
    monkeypatch.setattr(mod, "_run_pending_request", fake_run_pending)

    with pytest.raises(asyncio.CancelledError):
        await mod.bot_action_redis_listen_loop()

    assert seen[:2] == ["to_thread", "get:1.0"]
