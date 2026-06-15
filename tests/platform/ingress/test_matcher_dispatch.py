from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from nonebot.internal.rule import Rule
from nonebot.rule import command, to_me

from src.platform.ingress import matcher_activation as activation
from src.platform.ingress import matcher_dispatch as dispatch
from src.platform.ingress import message_load


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
