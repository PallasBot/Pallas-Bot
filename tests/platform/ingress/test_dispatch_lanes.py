from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.internal.rule import Rule
from nonebot.rule import command, to_me

from src.platform.ingress import dispatch_lanes, message_load
from src.platform.ingress.dispatch_lanes import DispatchLane, LaneController


class _CommandMatcher:
    plugin_name = "src.plugins.help"
    rule = Rule(command("foo"))


class _AiMatcher:
    plugin_name = "src.plugins.ollama"
    rule = Rule(to_me())


class _RegexMatcher:
    plugin_name = "src.plugins.duel"
    rule = Rule(to_me())


@pytest.fixture(autouse=True)
def reset_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.platform.ingress.fleet_dispatch_scale.connected_bot_count",
        lambda: 1,
    )
    dispatch_lanes.clear_dispatch_lanes_cache()
    dispatch_lanes.uninstall_dispatch_lanes()
    message_load.reset_message_load_for_tests()
    yield
    dispatch_lanes.clear_dispatch_lanes_cache()
    dispatch_lanes.uninstall_dispatch_lanes()
    message_load.reset_message_load_for_tests()


def test_normalize_lane_accepts_legacy_names() -> None:
    assert dispatch_lanes.normalize_lane("passive_ai") == DispatchLane.REMOTE
    assert dispatch_lanes.normalize_lane("command_exact") == DispatchLane.COMMAND
    assert dispatch_lanes.normalize_lane("passive_db") == DispatchLane.STORAGE


def test_lane_for_matcher_command_and_chat_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch_lanes, "plugin_lane_override", lambda _module: None)
    assert dispatch_lanes.lane_for_matcher(_CommandMatcher) == DispatchLane.COMMAND
    assert dispatch_lanes.lane_for_matcher(_AiMatcher) == DispatchLane.CHAT


def test_lane_for_matcher_uses_plugin_lane_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dispatch_lanes,
        "plugin_lane_override",
        lambda module: "remote" if module == "ollama" else None,
    )
    assert dispatch_lanes.lane_for_matcher(_AiMatcher) == DispatchLane.REMOTE


def test_storage_limit_tightens_under_pool_pressure(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = LaneController(DispatchLane.STORAGE, 8)
    monkeypatch.setattr(dispatch_lanes, "pg_pool_under_pressure", lambda **kwargs: False)
    assert controller.effective_limit() == 8
    monkeypatch.setattr(dispatch_lanes, "pg_pool_under_pressure", lambda **kwargs: True)
    assert controller.effective_limit() == 4


@pytest.mark.asyncio
async def test_lane_controller_blocks_when_full() -> None:
    controller = LaneController(DispatchLane.REMOTE, 1)
    ok1, _ = await controller.acquire(0.2)
    ok2, _ = await controller.acquire(0.05)
    assert ok1 is True
    assert ok2 is False
    await controller.release()
    ok3, _ = await controller.acquire(0.2)
    assert ok3 is True
    await controller.release()


@pytest.mark.asyncio
async def test_record_lane_wait_signals_overload() -> None:
    message_load.reset_message_load_for_tests()
    message_load.record_lane_wait(float(message_load.lane_wait_overload_threshold_ms()))
    assert message_load.should_pause_tasks() is True


@pytest.mark.asyncio
async def test_check_and_run_matcher_with_lane_skips_when_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch_lanes.install_dispatch_lanes()
    controller = dispatch_lanes.lane_controller(DispatchLane.REMOTE)
    assert controller is not None
    await controller.acquire(0.01)
    await controller.acquire(0.01)
    await controller.acquire(0.01)
    await controller.acquire(0.01)

    run_mock = AsyncMock()
    busy_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(dispatch_lanes, "plugin_lane_override", lambda module: "remote" if module == "ollama" else None)
    monkeypatch.setattr("nonebot.message.check_and_run_matcher", run_mock)
    monkeypatch.setattr(dispatch_lanes, "maybe_send_lane_busy_reply", busy_mock)

    result = await dispatch_lanes.check_and_run_matcher_with_lane(
        _AiMatcher,
        AsyncMock(),
        MagicMock(),
        {},
        MagicMock(),
        {},
        command_traffic=True,
        busy_reply_sent=False,
    )
    assert result.acquired is False
    assert result.lane_busy is True
    busy_mock.assert_not_awaited()
    run_mock.assert_not_awaited()
    for _ in range(4):
        await controller.release()


def test_install_dispatch_lanes_reads_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch_lanes, "repo_env_raw_value", lambda _key: None)
    monkeypatch.setattr(dispatch_lanes, "pg_pool_capacity", lambda: 30)
    dispatch_lanes.install_dispatch_lanes()
    controller = dispatch_lanes.lane_controller(DispatchLane.STORAGE)
    assert controller is not None
    assert controller.base_limit == 8
    assert dispatch_lanes.lane_controller(DispatchLane.REMOTE).base_limit == 4
