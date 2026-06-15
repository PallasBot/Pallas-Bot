from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.internal.rule import Rule
from nonebot.rule import command, to_me

from src.platform.ingress import dispatch_lanes, message_load
from src.platform.ingress import matcher_activation as activation
from src.platform.ingress import matcher_dispatch as dispatch


class _CommandMatcher:
    rule = Rule(command("foo"))


class _PassiveMatcher:
    rule = Rule(to_me())


class _EmptyMatcher:
    rule = Rule()


def test_matcher_is_command_only():
    assert activation.matcher_is_command_only(_CommandMatcher) is True
    assert activation.matcher_is_command_only(_PassiveMatcher) is False
    assert activation.matcher_is_command_only(_EmptyMatcher) is False


def test_select_priority_matchers_skips_commands_on_chatter():
    selected = activation.select_priority_matchers(
        [_CommandMatcher, _PassiveMatcher, _EmptyMatcher],
        command_traffic=False,
    )
    assert _CommandMatcher not in selected
    assert _PassiveMatcher in selected
    assert _EmptyMatcher in selected


def test_select_priority_matchers_keeps_all_on_command_traffic():
    pool = [_CommandMatcher, _PassiveMatcher]
    selected = activation.select_priority_matchers(pool, command_traffic=True)
    assert selected == pool


def test_message_load_overload_window():
    message_load.reset_message_load_for_tests()
    assert message_load.should_pause_tasks() is False
    message_load.signal_overload(0.2)
    assert message_load.is_overloaded() is True
    assert message_load.should_pause_tasks() is True


def test_matcher_dispatch_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "repo_env_raw_value", lambda _key: None)
    assert dispatch.matcher_dispatch_enabled() is True


def test_matcher_dispatch_can_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "repo_env_raw_value", lambda _key: "false")
    assert dispatch.matcher_dispatch_enabled() is False


def test_install_and_uninstall_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    import nonebot.message as nb_message

    original = nb_message.handle_event
    dispatch.uninstall_matcher_dispatch()
    monkeypatch.setattr(dispatch, "matcher_dispatch_enabled", lambda: True)
    try:
        dispatch.install_matcher_dispatch()
        assert dispatch.matcher_dispatch_installed() is True
        assert nb_message.handle_event is not original
        dispatch.uninstall_matcher_dispatch()
        assert nb_message.handle_event is original
    finally:
        dispatch.uninstall_matcher_dispatch()


def test_event_command_traffic_uses_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    event = MagicMock()
    event.get_plaintext.return_value = "牛牛帮助"
    monkeypatch.setattr(activation, "route_index_enabled", lambda: False)
    monkeypatch.setattr(activation, "is_plugin_command_plaintext", lambda text: text == "牛牛帮助")
    monkeypatch.setattr(activation.TrieRule.prefix, "longest_prefix", lambda _text: None)
    assert activation.event_command_traffic(event, {}) is True

    event.get_plaintext.return_value = "今天天气不错"
    monkeypatch.setattr(activation, "is_plugin_command_plaintext", lambda _text: False)
    assert activation.event_command_traffic(event, {}) is False


@pytest.mark.asyncio
async def test_patched_handle_event_skips_busy_reply_when_other_matcher_can_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGroupMessageEvent:
        raw_message = "foo"

        def get_log_string(self) -> str:
            return "fake group message"

        def get_plaintext(self) -> str:
            return "foo"

    class BusyMatcher:
        rule = Rule()

    class ReadyMatcher:
        rule = Rule()

    bot = MagicMock()
    bot.type = "OneBot V11"
    bot.self_id = "10001"
    event = FakeGroupMessageEvent()
    pre_mock = AsyncMock(return_value=True)
    post_mock = AsyncMock()
    busy_reply_mock = AsyncMock(return_value=True)

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_preprocessors", pre_mock)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_postprocessors", post_mock)
    monkeypatch.setattr("nonebot.message.check_and_run_matcher", AsyncMock())
    monkeypatch.setattr(dispatch.nb_message.TrieRule, "get_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "mark_activity", lambda: None)
    monkeypatch.setattr(dispatch, "resolve_route_for_event", lambda _event: None)
    monkeypatch.setattr(dispatch, "event_command_traffic", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(dispatch, "select_priority_matchers", lambda priority_matchers, **_kwargs: priority_matchers)
    monkeypatch.setattr(dispatch, "record_group_message_ingress", lambda **_kwargs: None)
    monkeypatch.setattr(dispatch, "signal_overload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "overload_selected_threshold", lambda: 99)
    monkeypatch.setattr(dispatch, "matchers", {1: [BusyMatcher, ReadyMatcher]})
    monkeypatch.setattr(
        dispatch_lanes,
        "lane_for_matcher",
        lambda matcher: (
            dispatch_lanes.DispatchLane.REMOTE if matcher is BusyMatcher else dispatch_lanes.DispatchLane.COMMAND
        ),
    )
    monkeypatch.setattr(dispatch_lanes, "maybe_send_lane_busy_reply", busy_reply_mock)

    dispatch_lanes.install_dispatch_lanes()
    controller = dispatch_lanes.lane_controller(dispatch_lanes.DispatchLane.REMOTE)
    assert controller is not None
    for _ in range(controller.base_limit):
        ok, _ = await controller.acquire(0.01)
        assert ok is True

    await dispatch.patched_handle_event(bot, event)

    busy_reply_mock.assert_not_awaited()
    pre_mock.assert_awaited_once()
    post_mock.assert_awaited_once()

    for _ in range(controller.base_limit):
        await controller.release()
    dispatch_lanes.uninstall_dispatch_lanes()


@pytest.mark.asyncio
async def test_patched_handle_event_sends_busy_reply_when_all_selected_matchers_are_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGroupMessageEvent:
        raw_message = "foo"

        def get_log_string(self) -> str:
            return "fake group message"

        def get_plaintext(self) -> str:
            return "foo"

    class BusyMatcher:
        rule = Rule()

    bot = MagicMock()
    bot.type = "OneBot V11"
    bot.self_id = "10001"
    event = FakeGroupMessageEvent()
    pre_mock = AsyncMock(return_value=True)
    post_mock = AsyncMock()
    busy_reply_mock = AsyncMock(return_value=True)

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_preprocessors", pre_mock)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_postprocessors", post_mock)
    monkeypatch.setattr("nonebot.message.check_and_run_matcher", AsyncMock())
    monkeypatch.setattr(dispatch.nb_message.TrieRule, "get_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "mark_activity", lambda: None)
    monkeypatch.setattr(dispatch, "resolve_route_for_event", lambda _event: None)
    monkeypatch.setattr(dispatch, "event_command_traffic", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(dispatch, "select_priority_matchers", lambda priority_matchers, **_kwargs: priority_matchers)
    monkeypatch.setattr(dispatch, "record_group_message_ingress", lambda **_kwargs: None)
    monkeypatch.setattr(dispatch, "signal_overload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "overload_selected_threshold", lambda: 99)
    monkeypatch.setattr(dispatch, "matchers", {1: [BusyMatcher]})
    monkeypatch.setattr(dispatch_lanes, "lane_for_matcher", lambda _matcher: dispatch_lanes.DispatchLane.REMOTE)
    monkeypatch.setattr(dispatch, "maybe_send_lane_busy_reply", busy_reply_mock)

    dispatch_lanes.install_dispatch_lanes()
    controller = dispatch_lanes.lane_controller(dispatch_lanes.DispatchLane.REMOTE)
    assert controller is not None
    for _ in range(controller.base_limit):
        ok, _ = await controller.acquire(0.01)
        assert ok is True

    await dispatch.patched_handle_event(bot, event)

    busy_reply_mock.assert_awaited_once()
    pre_mock.assert_awaited_once()
    post_mock.assert_awaited_once()

    for _ in range(controller.base_limit):
        await controller.release()
    dispatch_lanes.uninstall_dispatch_lanes()
