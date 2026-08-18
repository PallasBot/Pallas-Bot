from __future__ import annotations

from unittest.mock import MagicMock

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


def test_is_retryable_classifies_network_and_media_errors() -> None:
    from nonebot.adapters.onebot.v11 import ActionFailed, NetworkError

    assert send_queue.is_retryable_send_error("send_group_msg", NetworkError("connection reset")) is True
    assert (
        send_queue.is_retryable_send_error(
            "send_group_msg",
            ActionFailed(retcode=100, message="HTTP download failed: 404"),
        )
        is True
    )
    assert (
        send_queue.is_retryable_send_error(
            "send_group_msg",
            ActionFailed(retcode=100, message="unclassified wording"),
        )
        is False
    )


def test_websocket_timeout_is_not_retryable() -> None:
    from nonebot.adapters.onebot.v11 import NetworkError

    timeout = NetworkError("WebSocket call api send_group_msg timeout")
    assert send_queue.is_ambiguous_send_timeout(timeout) is True
    assert send_queue.is_retryable_send_error("send_group_msg", timeout) is False
    assert send_queue.is_retryable_send_error("send_group_msg", NetworkError("boom")) is True


def test_is_risk_limited_detects_rate_limit_codes_and_wording() -> None:
    from nonebot.adapters.onebot.v11 import ActionFailed, NetworkError

    assert send_queue.is_risk_limited_send_error("send_group_msg", ActionFailed(retcode=1201)) is True
    assert (
        send_queue.is_risk_limited_send_error(
            "send_group_msg",
            ActionFailed(retcode=100, message="发送消息过于频繁"),
        )
        is True
    )
    assert send_queue.is_risk_limited_send_error("send_group_msg", NetworkError("boom")) is False
    assert send_queue.is_risk_limited_send_error("send_group_msg", ActionFailed(retcode=1200)) is False


def test_send_error_retry_delay_backs_off_for_network_and_uses_cooldown_for_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nonebot.adapters.onebot.v11 import ActionFailed, NetworkError

    monkeypatch.setattr(send_queue, "send_queue_retry_backoff_base_sec", lambda: 2.0)
    monkeypatch.setattr(send_queue, "send_queue_retry_risk_cooldown_sec", lambda: 45.0)
    assert send_queue.send_error_retry_delay_sec("send_group_msg", NetworkError("x"), attempt=1) == 2.0
    assert send_queue.send_error_retry_delay_sec("send_group_msg", NetworkError("x"), attempt=2) == 4.0
    assert send_queue.send_error_retry_delay_sec("send_group_msg", ActionFailed(retcode=1201), attempt=1) == 45.0


def test_note_send_risk_failure_arms_cooldown_after_latch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(send_queue, "send_queue_retry_risk_latch_times", lambda: 3)
    monkeypatch.setattr(send_queue, "send_queue_retry_risk_cooldown_sec", lambda: 60.0)
    for _ in range(2):
        send_queue.note_send_risk_failure("10001")
    assert send_queue.is_send_bot_in_risk_cooldown("10001") == 0.0
    assert send_queue._STATS["risk_cooldowns"] == 0

    send_queue.note_send_risk_failure("10001")
    assert send_queue.is_send_bot_in_risk_cooldown("10001") > 0.0
    assert send_queue._STATS["risk_cooldowns"] == 1


@pytest.mark.asyncio
async def test_network_error_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot.adapters.onebot.v11 import NetworkError

    calls = {"count": 0}

    async def flaky_original(adapter, bot, api, **data):
        calls["count"] += 1
        if calls["count"] == 1:
            raise NetworkError("boom")
        return {"message_id": 1}

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", flaky_original)
    monkeypatch.setattr(send_queue, "send_queue_retry_max", lambda: 2)
    monkeypatch.setattr(send_queue, "send_queue_retry_backoff_base_sec", lambda: 0.0)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    await send_queue.start_send_queue_workers()

    result = await send_queue.enqueue_call_api(MagicMock(), MagicMock(self_id="123"), "send_group_msg", message="hi")

    assert result == {"message_id": 1}
    assert calls["count"] == 2
    status = send_queue.send_queue_status()
    assert status["retries"] == 1
    assert status["sent"] == 1
    await send_queue.stop_send_queue_workers()


@pytest.mark.asyncio
async def test_risk_limited_error_sets_cooldown_and_still_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot.adapters.onebot.v11 import ActionFailed

    calls = {"count": 0}

    async def risk_original(adapter, bot, api, **data):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ActionFailed(retcode=1201, message="发送消息过于频繁")
        return {"message_id": 2}

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", risk_original)
    monkeypatch.setattr(send_queue, "send_queue_retry_max", lambda: 3)
    monkeypatch.setattr(send_queue, "send_queue_retry_risk_cooldown_sec", lambda: 0.0)
    monkeypatch.setattr(send_queue, "send_queue_retry_risk_latch_times", lambda: 3)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    await send_queue.start_send_queue_workers()

    result = await send_queue.enqueue_call_api(MagicMock(), MagicMock(self_id="123"), "send_group_msg", message="hi")

    assert result == {"message_id": 2}
    assert calls["count"] == 2
    assert send_queue._STATS["retries"] == 1
    assert send_queue._STATS["risk_cooldowns"] == 0
    await send_queue.stop_send_queue_workers()


@pytest.mark.asyncio
async def test_non_retryable_error_fails_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot.adapters.onebot.v11 import ActionFailed

    calls = {"count": 0}

    async def hard_fail(adapter, bot, api, **data):
        calls["count"] += 1
        raise ActionFailed(retcode=10004, message="参数错误")

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", hard_fail)
    monkeypatch.setattr(send_queue, "send_queue_retry_max", lambda: 2)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    await send_queue.start_send_queue_workers()

    with pytest.raises(ActionFailed):
        await send_queue.enqueue_call_api(MagicMock(), MagicMock(self_id="123"), "send_group_msg", message="hi")

    assert calls["count"] == 1
    status = send_queue.send_queue_status()
    assert status["retries"] == 0
    assert status["errors"] == 1
    await send_queue.stop_send_queue_workers()


@pytest.mark.asyncio
async def test_websocket_timeout_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot.adapters.onebot.v11 import NetworkError

    calls = {"count": 0}

    async def timeout_original(adapter, bot, api, **data):
        calls["count"] += 1
        raise NetworkError("WebSocket call api send_group_msg timeout")

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", timeout_original)
    monkeypatch.setattr(send_queue, "send_queue_retry_max", lambda: 2)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    await send_queue.start_send_queue_workers()

    with pytest.raises(NetworkError):
        await send_queue.enqueue_call_api(MagicMock(), MagicMock(self_id="123"), "send_group_msg", message="hi")

    assert calls["count"] == 1
    status = send_queue.send_queue_status()
    assert status["retries"] == 0
    assert status["errors"] == 1
    await send_queue.stop_send_queue_workers()


@pytest.mark.asyncio
async def test_retries_exhausted_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot.adapters.onebot.v11 import NetworkError

    calls = {"count": 0}

    async def always_fail(adapter, bot, api, **data):
        calls["count"] += 1
        raise NetworkError("connection reset")

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", always_fail)
    monkeypatch.setattr(send_queue, "send_queue_retry_max", lambda: 2)
    monkeypatch.setattr(send_queue, "send_queue_retry_backoff_base_sec", lambda: 0.0)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    await send_queue.start_send_queue_workers()

    with pytest.raises(NetworkError):
        await send_queue.enqueue_call_api(MagicMock(), MagicMock(self_id="123"), "send_group_msg", message="hi")

    assert calls["count"] == 3
    status = send_queue.send_queue_status()
    assert status["retries"] == 2
    assert status["errors"] == 3
    await send_queue.stop_send_queue_workers()


@pytest.mark.asyncio
async def test_cooldown_delays_re_enqueue_until_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    calls = {"count": 0}

    async def ok_original(adapter, bot, api, **data):
        calls["count"] += 1
        return {"message_id": 9}

    monkeypatch.setattr(send_queue, "_ORIGINAL_CALL_API", ok_original)
    monkeypatch.setattr(send_queue, "send_queue_retry_max", lambda: 3)
    monkeypatch.setattr(send_queue, "send_queue_retry_risk_cooldown_sec", lambda: 0.3)
    monkeypatch.setattr(send_queue, "send_queue_retry_risk_latch_times", lambda: 1)
    monkeypatch.setattr(send_queue, "send_queue_min_interval_sec", lambda: 0.0)
    await send_queue.start_send_queue_workers()

    send_queue.note_send_risk_failure("777")
    assert send_queue.is_send_bot_in_risk_cooldown("777") > 0.0

    started = time.monotonic()
    result = await send_queue.enqueue_call_api(MagicMock(), MagicMock(self_id="777"), "send_group_msg", message="hi")
    elapsed = time.monotonic() - started

    assert result == {"message_id": 9}
    assert calls["count"] == 1
    assert elapsed >= 0.25
    assert send_queue._STATS["risk_cooldowns"] == 1
    await send_queue.stop_send_queue_workers()
