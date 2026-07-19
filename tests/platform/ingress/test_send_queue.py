from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.core.platform.ingress import message_load, send_queue


@pytest.fixture(autouse=True)
def reset_send_queue() -> None:
    send_queue.reset_send_queue_for_tests()
    message_load.reset_message_load_for_tests()
    send_queue.uninstall_send_queue()
    yield
    send_queue.reset_send_queue_for_tests()
    message_load.reset_message_load_for_tests()
    send_queue.uninstall_send_queue()


def test_should_queue_send_apis() -> None:
    assert send_queue.should_queue_api("send_group_msg") is True
    assert send_queue.should_queue_api("set_msg_emoji_like") is True
    assert send_queue.should_queue_api("get_group_list") is False


def test_api_send_priority() -> None:
    assert send_queue.api_send_priority("send_group_msg") < send_queue.api_send_priority("group_poke")


@pytest.mark.asyncio
async def test_enqueue_executes_via_original_call_api(monkeypatch: pytest.MonkeyPatch) -> None:
    original = AsyncMock(return_value={"message_id": 1})
    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", original)
    monkeypatch.setattr(send_queue, "send_queue_max_depth", lambda: 64)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    await send_queue.start_send_queue_workers()

    adapter = MagicMock()
    bot = MagicMock(self_id="123")
    result = await send_queue.enqueue_call_api(adapter, bot, "send_group_msg", group_id=1, message="hi")

    assert result == {"message_id": 1}
    original.assert_awaited_once()
    await send_queue.stop_send_queue_workers()


@pytest.mark.asyncio
async def test_droppable_api_skipped_when_depth_high(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(send_queue, "send_queue_max_depth", lambda: 10)
    await send_queue.start_send_queue_workers()
    send_queue._STATS["depth"] = 6

    result = await send_queue.enqueue_call_api(MagicMock(), MagicMock(), "set_msg_emoji_like", message_id=1)

    assert result is None
    assert send_queue._STATS["dropped"] == 1
    await send_queue.stop_send_queue_workers()


@pytest.mark.asyncio
async def test_patched_call_api_bypasses_for_non_send_api(monkeypatch: pytest.MonkeyPatch) -> None:
    original = AsyncMock(return_value={"groups": []})
    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", original)

    result = await send_queue.patched_call_api(MagicMock(), MagicMock(), "get_group_list")

    assert result == {"groups": []}
    original.assert_awaited_once()


def test_install_and_uninstall_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot.adapters.onebot.v11.adapter import Adapter

    original = Adapter._call_api
    monkeypatch.setattr(send_queue, "send_queue_enabled", lambda: True)
    try:
        send_queue.install_send_queue()
        assert send_queue.send_queue_installed() is True
        assert Adapter._call_api is not original
        send_queue.uninstall_send_queue()
        assert Adapter._call_api is original
    finally:
        send_queue.uninstall_send_queue()


def test_record_send_queue_pressure_signals_overload() -> None:
    message_load.reset_message_load_for_tests()
    message_load.record_send_queue_pressure(220, 256)
    assert message_load.should_pause_tasks() is True
