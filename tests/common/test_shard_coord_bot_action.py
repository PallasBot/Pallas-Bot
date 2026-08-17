from __future__ import annotations

import asyncio
import base64
import time

import pytest

from pallas.core.platform.shard.coord import bot_action as mod


def test_message_from_payload_appends_multiple_images() -> None:
    payload = {
        "message_text": "album",
        "image_b64_list": [
            base64.b64encode(b"one").decode("ascii"),
            base64.b64encode(b"two").decode("ascii"),
        ],
    }

    message = mod._message_from_payload(payload)

    assert isinstance(message, mod.Message)
    assert str(message).count("[CQ:image") == 2


def test_put_image_bytes_keeps_legacy_single_image_payload() -> None:
    payload: dict[str, object] = {}

    mod._put_image_bytes(payload, b"one")

    assert "image_b64" in payload
    assert "image_b64_list" not in payload


def test_put_image_bytes_uses_list_payload_for_multiple_images() -> None:
    payload: dict[str, object] = {}

    mod._put_image_bytes(payload, [b"one", b"two"])

    assert "image_b64" not in payload
    assert len(payload["image_b64_list"]) == 2


@pytest.mark.asyncio
async def test_send_group_forward_message_normalizes_message_content(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def fake_invoke(action, bot_qq, payload, *, timeout_sec):
        seen.update(action=action, bot_qq=bot_qq, payload=payload, timeout_sec=timeout_sec)
        return True, None

    monkeypatch.setattr(mod, "invoke_bot_action", fake_invoke)

    ok = await mod.send_group_forward_message_as_bot(
        300,
        733291779,
        [{"data": {"name": "B站动态", "content": mod.Message("text")}}],
    )

    assert ok is True
    assert seen["action"] == "send_group_forward_msg"
    assert seen["payload"]["messages"][0]["data"]["content"] == "text"


def test_start_bot_action_redis_listener_starts_when_coord_enabled(fake_coord_redis, monkeypatch):
    started: list[object] = []

    def fake_create_task(coro):
        started.append(coro)
        return object()

    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(mod, "_listener_started", False)
    mod.start_bot_action_redis_listener()
    assert len(started) == 1
    assert mod._listener_started is True


def test_start_bot_action_redis_listener_starts_even_without_coord(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.coord.redis_settings.coord_redis_enabled",
        lambda: False,
    )
    monkeypatch.setattr(mod, "_listener_started", False)
    started: list[object] = []

    def fake_create_task(coro):
        started.append(coro)
        return object()

    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task)
    mod.start_bot_action_redis_listener()
    assert len(started) == 1
    assert mod._listener_started is True


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
@pytest.mark.asyncio
async def test_execute_local_repeater_fanout_reply_preserves_stagger_delay(monkeypatch):
    delayed: list[float] = []

    scheduled = []

    def fake_create_task(coro, *, name=None):
        scheduled.append(coro)
        return object()

    async def fake_sleep(delay: float) -> None:
        delayed.append(delay)

    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr("nonebot.get_bots", lambda: {"300": object()})

    async def fake_run_repeater_reply_for_bot(_bot_id: int, _payload: dict[str, object]) -> None:
        return None

    from packages.repeater import fanout_reply as fanout_mod

    monkeypatch.setattr(fanout_mod, "run_repeater_reply_for_bot", fake_run_repeater_reply_for_bot)

    await mod._execute_local("repeater_fanout_reply", 300, {"group_id": 1, "delay_sec": 0.35})
    await scheduled[0]

    assert delayed == [0.35]


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

    from packages.repeater import fanout_reply as fanout_mod

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
    monkeypatch.setattr("pallas.core.platform.coord.redis_settings.coord_redis_enabled", lambda: True)
    monkeypatch.setattr("pallas.core.platform.coord.redis_claim.get_coord_redis_client", lambda: _Client())
    monkeypatch.setattr(mod, "_run_pending_request", fake_run_pending)

    with pytest.raises(asyncio.CancelledError):
        await mod.bot_action_redis_listen_loop()

    assert seen[:2] == ["to_thread", "get:1.0"]
