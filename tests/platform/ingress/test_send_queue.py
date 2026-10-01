from __future__ import annotations

import asyncio
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
async def test_cancelled_queued_send_is_not_executed_later(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def original(_adapter, _bot, _api, *, number: int):
        calls.append(number)
        if number == 1:
            first_started.set()
            await release_first.wait()
        return number

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", original)
    monkeypatch.setattr(send_queue, "send_queue_worker_count", lambda: 1)
    monkeypatch.setattr(send_queue, "send_queue_max_depth", lambda: 2)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    await send_queue.start_send_queue_workers()
    first = asyncio.create_task(send_queue.enqueue_call_api(MagicMock(), MagicMock(), "send_group_msg", number=1))
    second = asyncio.create_task(send_queue.enqueue_call_api(MagicMock(), MagicMock(), "send_group_msg", number=2))
    third = None
    try:
        await first_started.wait()
        for _ in range(20):
            if send_queue._STATS["enqueued"] == 2:
                break
            await asyncio.sleep(0)
        assert send_queue._STATS["depth"] == 2
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        assert send_queue._STATS["depth"] == 2
        third = asyncio.create_task(send_queue.enqueue_call_api(MagicMock(), MagicMock(), "send_group_msg", number=3))
        await asyncio.sleep(0.01)
        assert not third.done()
        release_first.set()
        assert await first == 1
        assert await third == 3
        queue = send_queue._QUEUE
        if queue is not None:
            await asyncio.wait_for(queue.join(), timeout=0.2)
        assert calls == [1, 3]
        assert send_queue._STATS["depth"] == 0
    finally:
        release_first.set()
        await send_queue.stop_send_queue_workers()
        await asyncio.gather(first, second, *([third] if third is not None else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_send_during_rate_limit_wait_never_reaches_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    waiting = asyncio.Event()
    release = asyncio.Event()
    original = AsyncMock()

    async def rate_limit_wait(_bot_id: str) -> None:
        waiting.set()
        await release.wait()

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", original)
    monkeypatch.setattr(send_queue, "_rate_limit_wait", rate_limit_wait)
    await send_queue.start_send_queue_workers()
    caller = asyncio.create_task(send_queue.enqueue_call_api(MagicMock(), MagicMock(), "send_group_msg"))
    try:
        await asyncio.wait_for(waiting.wait(), timeout=0.2)
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        release.set()
        assert send_queue._QUEUE is not None
        await asyncio.wait_for(send_queue._QUEUE.join(), timeout=0.2)
        original.assert_not_awaited()
    finally:
        release.set()
        await send_queue.stop_send_queue_workers()
        await asyncio.gather(caller, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_caller_during_send_keeps_capacity_until_adapter_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_original(*_args, **_kwargs):
        started.set()
        await release.wait()
        return {"message_id": 1}

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", blocked_original)
    monkeypatch.setattr(send_queue, "send_queue_max_depth", lambda: 1)
    await send_queue.start_send_queue_workers()
    caller = asyncio.create_task(send_queue.enqueue_call_api(MagicMock(), MagicMock(), "send_group_msg"))
    try:
        await started.wait()
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        assert send_queue.send_queue_status()["depth"] == 1
        assert send_queue._STATS["enqueued"] == 1
        release.set()
        assert send_queue._QUEUE is not None
        await asyncio.wait_for(send_queue._QUEUE.join(), timeout=0.2)
        assert send_queue.send_queue_status()["depth"] == 0
        assert send_queue._STATS["sent"] == 1
    finally:
        release.set()
        await send_queue.stop_send_queue_workers()
        await asyncio.gather(caller, return_exceptions=True)


@pytest.mark.asyncio
async def test_stopping_during_send_finishes_waiting_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()

    async def blocked_original(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", blocked_original)
    await send_queue.start_send_queue_workers()
    caller = asyncio.create_task(send_queue.enqueue_call_api(MagicMock(), MagicMock(), "send_group_msg"))
    try:
        await started.wait()
        queue = send_queue._QUEUE
        await asyncio.gather(send_queue.stop_send_queue_workers(), send_queue.stop_send_queue_workers())
        done, _pending = await asyncio.wait({caller}, timeout=0.05)
        assert caller in done
        assert queue is not None
        assert queue._unfinished_tasks == 0
        assert send_queue.send_queue_status()["depth"] == 0
        with pytest.raises(RuntimeError, match="stopped"):
            caller.result()
    finally:
        await send_queue.stop_send_queue_workers()
        if not caller.done():
            caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelling_stop_caller_does_not_leave_queue_stopping(monkeypatch: pytest.MonkeyPatch) -> None:
    worker_started = asyncio.Event()
    worker_cancelled = asyncio.Event()
    release_worker = asyncio.Event()

    async def slow_cancelled_worker(_worker_id: int) -> None:
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            worker_cancelled.set()
            await release_worker.wait()
            raise

    monkeypatch.setattr(send_queue, "_send_queue_worker", slow_cancelled_worker)
    await send_queue.start_send_queue_workers()
    await worker_started.wait()
    stopping = asyncio.create_task(send_queue.stop_send_queue_workers())
    try:
        await worker_cancelled.wait()
        stopping.cancel()
        await asyncio.gather(stopping, return_exceptions=True)
        release_worker.set()
        assert send_queue._STOP_COMPLETE is not None
        await asyncio.wait_for(send_queue._STOP_COMPLETE.wait(), timeout=0.2)
        assert not send_queue._STOPPING
        await send_queue.start_send_queue_workers()
        assert send_queue._QUEUE is not None
    finally:
        release_worker.set()
        await send_queue.stop_send_queue_workers()
        await asyncio.gather(stopping, return_exceptions=True)


@pytest.mark.asyncio
async def test_send_queue_attributes_failures_without_exposing_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot.adapters.onebot.v11 import ActionFailed

    original = AsyncMock(
        side_effect=ActionFailed(
            status="failed",
            retcode=1200,
            message="sensitive message body",
        )
    )
    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", original)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    await send_queue.start_send_queue_workers()

    with pytest.raises(ActionFailed):
        await send_queue.enqueue_call_api(
            MagicMock(),
            MagicMock(self_id="123"),
            "send_group_msg",
            group_id=1,
            message="private content",
        )

    status = send_queue.send_queue_status()
    assert status["errors_by_api"] == {"send_group_msg": 1}
    assert status["errors_by_class"] == {"ActionFailed": 1}
    assert status["errors_by_retcode"] == {"1200": 1}
    assert set(status["last_error"]) == {"api", "error_class", "retcode", "reason", "age_sec"}
    assert status["last_error"]["api"] == "send_group_msg"
    assert status["last_error"]["error_class"] == "ActionFailed"
    assert status["last_error"]["retcode"] == 1200
    assert status["last_error"]["reason"] == "other"
    assert "sensitive" not in str(status)
    assert "private content" not in str(status)

    await send_queue.stop_send_queue_workers()


def test_send_queue_error_dimensions_are_bounded_and_resettable() -> None:
    from nonebot.adapters.onebot.v11 import ActionFailed

    for retcode in range(20):
        send_queue.record_send_queue_error(
            f"api_{retcode}",
            ActionFailed(retcode=retcode),
        )

    status = send_queue.send_queue_status()
    assert len(status["errors_by_api"]) == 16
    assert len(status["errors_by_retcode"]) == 16
    assert status["errors_by_api"]["other"] == 5
    assert status["errors_by_retcode"]["other"] == 5

    send_queue.reset_send_queue_for_tests()
    status = send_queue.send_queue_status()
    assert status["errors_by_api"] == {}
    assert status["errors_by_class"] == {}
    assert status["errors_by_retcode"] == {}
    assert status["errors_by_reason"] == {}
    assert status["last_error"] is None


@pytest.mark.parametrize(
    ("api", "message", "reason"),
    [
        ("set_msg_emoji_like", "OIDB error 65002: 已经设置过该表情", "already_reacted"),
        ("set_msg_emoji_like", "message not found", "message_not_found"),
        ("send_group_msg", "发送失败，你已被移出该群，请重新加群。", "bot_not_in_group"),
        ("send_group_msg", "HTTP download failed: 404", "media_download_failed"),
        ("send_group_msg", "unclassified sensitive wording", "other"),
    ],
)
def test_send_queue_classifies_failure_reason_without_exposing_wording(api: str, message: str, reason: str) -> None:
    from nonebot.adapters.onebot.v11 import ActionFailed

    send_queue.record_send_queue_error(api, ActionFailed(retcode=100, message=message))

    status = send_queue.send_queue_status()
    assert status["errors_by_reason"] == {reason: 1}
    assert status["last_error"]["reason"] == reason
    assert message not in str(status)


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
