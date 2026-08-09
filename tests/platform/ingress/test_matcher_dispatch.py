from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.exception import IgnoredException
from nonebot.internal.rule import Rule
from nonebot.rule import command, to_me

from pallas.core.perm import group_message_permission_for_command
from pallas.core.platform.ingress import dispatch_lanes, message_load
from pallas.core.platform.ingress import matcher_activation as activation
from pallas.core.platform.ingress import matcher_dispatch as dispatch
from pallas.core.platform.ingress.route_index import RouteResolution
from pallas.core.platform.message_runtime.models import HandlingOutcome, HandlingPlan, SendAction


def test_synthetic_llm_command_context_reads_structured_marker() -> None:
    event = MagicMock()
    event._pallas_llm_command_context = {
        "command_id": "memes.recommend",
        "source_segment_types": ["at"],
    }
    assert dispatch.synthetic_llm_command_context(event) == {
        "command_id": "memes.recommend",
        "source_segment_types": ["at"],
    }


def test_synthetic_llm_command_selects_only_its_routed_plugin_matchers() -> None:
    class MemesMatcher:
        plugin_name = "memes"

    class BlockingOtherMatcher:
        plugin_name = "other"
        block = True

    resolution = RouteResolution(frozenset({"memes"}), True)

    assert dispatch.select_synthetic_llm_command_matchers([BlockingOtherMatcher, MemesMatcher], resolution) == [
        MemesMatcher
    ]


def test_overload_chat_selection_keeps_only_core_reply_deciders() -> None:
    class RepeaterMatcher:
        plugin_name = "packages.repeater"

    class LlmMatcher:
        plugin_name = "packages.llm_chat"

    class GreetingMatcher:
        plugin_name = "packages.greeting"

    assert dispatch.select_overload_chatter_matchers([GreetingMatcher, RepeaterMatcher, LlmMatcher]) == [
        RepeaterMatcher,
        LlmMatcher,
    ]


def test_native_repeater_exclusion_keeps_other_passive_matchers() -> None:
    class RepeaterMatcher:
        plugin_name = "packages.repeater"

    class LlmMatcher:
        plugin_name = "packages.llm_chat"

    assert dispatch.exclude_native_matchers([RepeaterMatcher, LlmMatcher], frozenset({"repeater"})) == [LlmMatcher]


def test_message_runtime_context_treats_alias_hard_trigger_as_direct_address() -> None:
    bot = MagicMock(self_id="10001")
    event = MagicMock(group_id=42, message_id=3, to_me=False, _pallas_llm_alias_hard_trigger=True)
    event.get_plaintext.return_value = "牛牛出来"
    event.raw_message = "牛牛出来"

    context = dispatch.message_runtime_context(
        bot,
        event,
        command_traffic=False,
        resolution=RouteResolution(frozenset(), False),
    )

    assert context.is_to_me is True


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


def test_select_priority_matchers_skips_commands_on_chatter(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(activation, "chat_matcher_strict_enabled", lambda: False)
    monkeypatch.setattr(activation, "route_index_enabled", lambda: False)
    selected = activation.select_priority_matchers(
        [_CommandMatcher, _PassiveMatcher, _EmptyMatcher],
        command_traffic=False,
    )
    assert _CommandMatcher not in selected
    assert _PassiveMatcher in selected
    assert _EmptyMatcher in selected


def test_select_priority_matchers_strict_chat_keeps_passive_only(monkeypatch: pytest.MonkeyPatch):
    from pallas.core.platform.ingress import route_index

    class RepeaterMatcher:
        plugin_name = "packages.repeater"
        rule = Rule()

    class RandomMatcher:
        plugin_name = "packages.unknown_plugin"
        rule = Rule()

    snapshot = route_index.RouteIndexSnapshot(
        prefix_to_modules={},
        exact_to_modules={},
        regex_entries=(),
        always_run_modules=frozenset(),
        passive_modules=frozenset({"repeater"}),
        indexed_modules=frozenset(),
    )
    monkeypatch.setattr(activation, "route_index_enabled", lambda: True)
    monkeypatch.setattr(activation, "chat_matcher_strict_enabled", lambda: True)
    monkeypatch.setattr(activation, "get_route_index", lambda: snapshot)
    monkeypatch.setattr(activation, "resolve_route_for_event", lambda _e: None)
    resolution = route_index.RouteResolution(frozenset(), False)
    selected = activation.select_priority_matchers(
        [RepeaterMatcher, RandomMatcher, _CommandMatcher],
        command_traffic=False,
        resolution=resolution,
    )
    assert RepeaterMatcher in selected
    assert RandomMatcher not in selected
    assert _CommandMatcher not in selected


def test_select_priority_matchers_keeps_all_on_command_traffic():
    pool = [_CommandMatcher, _PassiveMatcher]
    selected = activation.select_priority_matchers(pool, command_traffic=True)
    assert selected == pool


class _GroupModeratorCommandMatcher:
    rule = Rule(command("牛牛进群欢迎"))
    permission = group_message_permission_for_command("greeting.set_group_welcome")


def test_select_priority_matchers_skips_group_moderator_command_for_normal_member() -> None:
    event = MagicMock()
    event.get_plaintext.return_value = "牛牛进群欢迎"
    event.raw_message = "牛牛进群欢迎"
    event.to_me = False
    event.get_type.return_value = "message"
    event.sender = MagicMock(role="member")

    selected = activation.select_priority_matchers(
        [_GroupModeratorCommandMatcher, _EmptyMatcher],
        command_traffic=True,
        event=event,
    )

    assert _GroupModeratorCommandMatcher not in selected
    assert _EmptyMatcher in selected


def test_message_load_overload_window():
    message_load.reset_message_load_for_tests()
    assert message_load.should_pause_tasks() is False
    message_load.signal_overload(0.2)
    assert message_load.is_overloaded() is True
    assert message_load.should_pause_tasks() is True
    assert message_load.should_shed_chat_sidework() is True


def test_chat_degraded_contextvar_roundtrip():
    message_load.reset_message_load_for_tests()
    assert message_load.is_chat_degraded() is False
    token = message_load.mark_chat_degraded(True)
    assert message_load.is_chat_degraded() is True
    assert message_load.should_shed_chat_sidework() is True
    message_load.reset_chat_degraded(token)
    assert message_load.is_chat_degraded() is False


@pytest.mark.asyncio
async def test_patched_handle_event_discards_pre_scheduler_federate_loser(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGroupMessageEvent:
        pass

    bot = MagicMock()
    event = FakeGroupMessageEvent()
    pre_gate = AsyncMock(side_effect=IgnoredException("federate ingress claim lost"))
    submit = AsyncMock()

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch, "conversation_scheduler_enabled", lambda: True)
    monkeypatch.setattr(dispatch, "pre_schedule_ingress_group_message_gate", pre_gate)
    monkeypatch.setattr(dispatch, "submit_conversation_event", submit)

    await dispatch.patched_handle_event(bot, event)

    pre_gate.assert_awaited_once_with(bot, event)
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_patched_handle_event_drops_chat_when_overloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGroupMessageEvent:
        group_id = 100
        message_id = 200
        raw_message = "今天天气不错"
        to_me = False

        def get_log_string(self) -> str:
            return "fake group message"

        def get_plaintext(self) -> str:
            return "今天天气不错"

    class PassiveMatcher:
        rule = Rule()

    bot = MagicMock()
    bot.type = "OneBot V11"
    bot.self_id = "10001"
    event = FakeGroupMessageEvent()
    pre_mock = AsyncMock(return_value=True)
    post_mock = AsyncMock()
    run_matcher = AsyncMock()
    experiment = MagicMock()
    experiment.plan = AsyncMock(return_value=HandlingPlan(kind="legacy", handler_ids=(), reason="chat_traffic"))

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_preprocessors", pre_mock)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_postprocessors", post_mock)
    monkeypatch.setattr("nonebot.message.check_and_run_matcher", run_matcher)
    monkeypatch.setattr(dispatch.nb_message.TrieRule, "get_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "mark_activity", lambda: None)
    monkeypatch.setattr(dispatch, "resolve_route_for_event", lambda _event: None)
    monkeypatch.setattr(dispatch, "event_command_traffic", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(dispatch, "chat_drop_on_overload_enabled", lambda: True)
    monkeypatch.setattr(dispatch, "is_overloaded", lambda: True)
    monkeypatch.setattr(dispatch, "record_chatter_overload_dropped", lambda: None)
    monkeypatch.setattr(dispatch, "record_group_message_ingress", lambda **_kwargs: None)
    monkeypatch.setattr(
        dispatch,
        "shadow_experiment_for_group",
        lambda group_id: experiment if group_id == 100 else None,
    )
    monkeypatch.setattr(dispatch, "matchers", {1: [PassiveMatcher]})

    await dispatch.patched_handle_event(bot, event)

    pre_mock.assert_awaited_once()
    post_mock.assert_awaited_once()
    run_matcher.assert_not_awaited()
    experiment.plan.assert_awaited_once()
    experiment.record_legacy.assert_called_once()


@pytest.mark.asyncio
async def test_patched_handle_event_degrades_chat_when_overloaded_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGroupMessageEvent:
        raw_message = "今天天气不错"

        def get_log_string(self) -> str:
            return "fake group message"

        def get_plaintext(self) -> str:
            return "今天天气不错"

    class PassiveMatcher:
        rule = Rule()

    bot = MagicMock()
    bot.type = "OneBot V11"
    bot.self_id = "10001"
    event = FakeGroupMessageEvent()
    pre_mock = AsyncMock(return_value=True)
    post_mock = AsyncMock()
    degraded = {"n": 0}
    tokens: list[object] = []

    async def fake_check_and_run(*_args, **_kwargs):
        from pallas.core.platform.ingress import message_load

        assert message_load.is_chat_degraded() is True
        return MagicMock(acquired=True)

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_preprocessors", pre_mock)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_postprocessors", post_mock)
    monkeypatch.setattr(dispatch.nb_message.TrieRule, "get_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "mark_activity", lambda: None)
    monkeypatch.setattr(dispatch, "resolve_route_for_event", lambda _event: None)
    monkeypatch.setattr(dispatch, "event_command_traffic", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(dispatch, "chat_drop_on_overload_enabled", lambda: False)
    monkeypatch.setattr(dispatch, "is_overloaded", lambda: True)

    def _bump_degraded() -> None:
        degraded["n"] += 1

    monkeypatch.setattr(dispatch, "record_chatter_overload_degraded", _bump_degraded)
    monkeypatch.setattr(dispatch, "record_group_message_ingress", lambda **_kwargs: None)
    monkeypatch.setattr(dispatch, "select_priority_matchers", lambda pool, **_kwargs: list(pool))
    monkeypatch.setattr(dispatch, "check_and_run_matcher_with_lane", fake_check_and_run)
    monkeypatch.setattr(dispatch, "matcher_dispatch_batches", lambda selected: [selected])
    monkeypatch.setattr(dispatch, "overload_selected_threshold", lambda: 99)
    monkeypatch.setattr(dispatch, "signal_overload", lambda *_a, **_k: None)
    monkeypatch.setattr(dispatch, "matchers", {1: [PassiveMatcher]})

    real_mark = dispatch.mark_chat_degraded
    real_reset = dispatch.reset_chat_degraded

    def tracking_mark(enabled: bool = True):
        token = real_mark(enabled)
        tokens.append(token)
        return token

    monkeypatch.setattr(dispatch, "mark_chat_degraded", tracking_mark)
    monkeypatch.setattr(dispatch, "reset_chat_degraded", real_reset)

    await dispatch.patched_handle_event(bot, event)

    assert degraded["n"] == 1
    assert tokens
    pre_mock.assert_awaited_once()
    post_mock.assert_awaited_once()
    from pallas.core.platform.ingress import message_load

    assert message_load.is_chat_degraded() is False


@pytest.mark.asyncio
async def test_shadow_runtime_plans_after_preprocessing_and_keeps_legacy_matchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGroupMessageEvent:
        group_id = 100
        message_id = 200
        raw_message = "#pallas"
        to_me = False

        def get_log_string(self) -> str:
            return "fake group message"

        def get_plaintext(self) -> str:
            return "#pallas"

    class StatusMatcher:
        plugin_name = "pb_core"
        rule = Rule()

    bot = MagicMock(type="OneBot V11", self_id="10001")
    event = FakeGroupMessageEvent()
    pre_mock = AsyncMock(return_value=True)
    post_mock = AsyncMock()
    experiment = MagicMock()
    experiment.plan = AsyncMock(return_value=HandlingPlan(kind="legacy", handler_ids=(), reason="unregistered"))

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_preprocessors", pre_mock)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_postprocessors", post_mock)
    monkeypatch.setattr(dispatch.nb_message.TrieRule, "get_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "mark_activity", lambda: None)
    monkeypatch.setattr(
        dispatch,
        "resolve_route_for_event",
        lambda _event: RouteResolution(frozenset({"pb_core"}), True),
    )
    monkeypatch.setattr(dispatch, "event_command_traffic", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(dispatch, "is_overloaded", lambda: False)
    monkeypatch.setattr(dispatch, "select_priority_matchers", lambda pool, **_kwargs: list(pool))
    monkeypatch.setattr(dispatch, "check_and_run_matcher_with_lane", AsyncMock(return_value=MagicMock(acquired=True)))
    monkeypatch.setattr(dispatch, "matcher_dispatch_batches", lambda selected: [selected])
    monkeypatch.setattr(dispatch, "overload_selected_threshold", lambda: 99)
    monkeypatch.setattr(dispatch, "signal_overload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "record_group_message_ingress", lambda **_kwargs: None)
    monkeypatch.setattr(
        dispatch,
        "shadow_experiment_for_group",
        lambda group_id: experiment if group_id == 100 else None,
    )
    monkeypatch.setattr(dispatch, "matchers", {1: [StatusMatcher]})

    await dispatch.patched_handle_event(bot, event)

    pre_mock.assert_awaited_once()
    experiment.plan.assert_awaited_once()
    context = experiment.plan.await_args.args[0]
    assert context.group_id == 100
    assert context.route_modules == frozenset({"pb_core"})
    experiment.record_legacy.assert_called_once()
    post_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_runtime_sends_once_and_skips_legacy_matchers(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGroupMessageEvent:
        group_id = 100
        message_id = 200
        raw_message = "#pallas"
        to_me = False

        def get_log_string(self) -> str:
            return "fake group message"

        def get_plaintext(self) -> str:
            return "#pallas"

    class StatusMatcher:
        plugin_name = "pb_core"
        rule = Rule()

    bot = MagicMock(type="OneBot V11", self_id="10001")
    bot.send = AsyncMock()
    event = FakeGroupMessageEvent()
    pre_mock = AsyncMock(return_value=True)
    post_mock = AsyncMock()
    native_runtime = MagicMock()
    native_runtime.execute_and_commit = AsyncMock(
        return_value=HandlingOutcome(handled=True, actions=(SendAction("status"),))
    )
    run_matcher = AsyncMock(return_value=MagicMock(acquired=True))

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_preprocessors", pre_mock)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_postprocessors", post_mock)
    monkeypatch.setattr(dispatch.nb_message.TrieRule, "get_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "mark_activity", lambda: None)
    monkeypatch.setattr(
        dispatch,
        "resolve_route_for_event",
        lambda _event: RouteResolution(frozenset({"pb_core"}), True),
    )
    monkeypatch.setattr(dispatch, "event_command_traffic", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        dispatch, "native_runtime_for_group", lambda group_id: native_runtime if group_id == 100 else None
    )
    monkeypatch.setattr(dispatch, "shadow_experiment_for_group", lambda _group_id: None)
    monkeypatch.setattr(dispatch, "record_route_index_decision", lambda **_kwargs: None)
    monkeypatch.setattr(dispatch, "record_group_message_ingress", lambda **_kwargs: None)
    monkeypatch.setattr(dispatch, "check_and_run_matcher_with_lane", run_matcher)
    monkeypatch.setattr(dispatch, "matchers", {1: [StatusMatcher]})

    await dispatch.patched_handle_event(bot, event)

    native_runtime.execute_and_commit.assert_awaited_once()
    bot.send.assert_not_awaited()
    run_matcher.assert_not_awaited()
    post_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_runtime_fallback_keeps_legacy_matchers(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGroupMessageEvent:
        group_id = 100
        message_id = 200
        raw_message = "#pallas details"
        to_me = False

        def get_log_string(self) -> str:
            return "fake group message"

        def get_plaintext(self) -> str:
            return "#pallas details"

    class StatusMatcher:
        plugin_name = "pb_core"
        rule = Rule()

    bot = MagicMock(type="OneBot V11", self_id="10001")
    event = FakeGroupMessageEvent()
    native_runtime = MagicMock()
    native_runtime.execute_and_commit = AsyncMock(return_value=HandlingOutcome(handled=False, fallback_to_legacy=True))
    run_matcher = AsyncMock(return_value=MagicMock(acquired=True))

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_preprocessors", AsyncMock(return_value=True))
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_postprocessors", AsyncMock())
    monkeypatch.setattr(dispatch.nb_message.TrieRule, "get_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "mark_activity", lambda: None)
    monkeypatch.setattr(
        dispatch,
        "resolve_route_for_event",
        lambda _event: RouteResolution(frozenset({"pb_core"}), True),
    )
    monkeypatch.setattr(dispatch, "event_command_traffic", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(dispatch, "native_runtime_for_group", lambda _group_id: native_runtime)
    monkeypatch.setattr(dispatch, "shadow_experiment_for_group", lambda _group_id: None)
    monkeypatch.setattr(dispatch, "record_route_index_decision", lambda **_kwargs: None)
    monkeypatch.setattr(dispatch, "record_group_message_ingress", lambda **_kwargs: None)
    monkeypatch.setattr(dispatch, "select_priority_matchers", lambda pool, **_kwargs: list(pool))
    monkeypatch.setattr(dispatch, "matcher_dispatch_batches", lambda selected: [selected])
    monkeypatch.setattr(dispatch, "overload_selected_threshold", lambda: 99)
    monkeypatch.setattr(dispatch, "signal_overload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "check_and_run_matcher_with_lane", run_matcher)
    monkeypatch.setattr(dispatch, "matchers", {1: [StatusMatcher]})

    await dispatch.patched_handle_event(bot, event)

    native_runtime.execute_and_commit.assert_awaited_once()
    run_matcher.assert_awaited_once()
    post = dispatch.nb_message._apply_event_postprocessors
    post.assert_awaited_once()


def test_chat_drop_on_overload_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "repo_env_raw_value", lambda _key: None)
    assert dispatch.chat_drop_on_overload_enabled() is False


def test_matcher_dispatch_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "repo_env_raw_value", lambda _key: None)
    assert dispatch.matcher_dispatch_enabled() is True


def test_matcher_dispatch_can_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatch, "repo_env_raw_value", lambda _key: "false")
    assert dispatch.matcher_dispatch_enabled() is False


@pytest.mark.asyncio
async def test_group_event_is_submitted_before_matcher_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass
    class FakeGroupMessageEvent:
        group_id: int

    bot = MagicMock(self_id="10001", type="OneBot V11")
    event = FakeGroupMessageEvent(group_id=12345)
    submitted: list[tuple[str, int]] = []
    run_now = AsyncMock()

    async def submit(inbound_bot, inbound_event, work) -> None:
        submitted.append((str(inbound_bot.self_id), inbound_event.group_id))
        await work()

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch, "conversation_scheduler_enabled", lambda: True)
    monkeypatch.setattr(dispatch, "submit_conversation_event", submit)
    monkeypatch.setattr(dispatch, "patched_handle_event_now", run_now)

    await dispatch.patched_handle_event(bot, event)

    assert submitted == [("10001", 12345)]
    run_now.assert_awaited_once_with(bot, event)


@pytest.mark.asyncio
async def test_non_group_event_bypasses_conversation_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGroupMessageEvent:
        pass

    bot = MagicMock()
    event = MagicMock(spec=[])
    submit = AsyncMock()
    run_now = AsyncMock()

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch, "conversation_scheduler_enabled", lambda: True)
    monkeypatch.setattr(dispatch, "submit_conversation_event", submit)
    monkeypatch.setattr(dispatch, "patched_handle_event_now", run_now)

    await dispatch.patched_handle_event(bot, event)

    submit.assert_not_awaited()
    run_now.assert_awaited_once_with(bot, event)


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

    dispatch_lanes.install_dispatch_lanes()
    controller = dispatch_lanes.lane_controller(dispatch_lanes.DispatchLane.REMOTE)
    assert controller is not None
    for _ in range(controller.base_limit):
        ok, _ = await controller.acquire(0.01)
        assert ok is True

    await dispatch.patched_handle_event(bot, event)

    pre_mock.assert_awaited_once()
    post_mock.assert_awaited_once()

    for _ in range(controller.base_limit):
        await controller.release()
    dispatch_lanes.uninstall_dispatch_lanes()


@pytest.mark.asyncio
async def test_patched_handle_event_stays_silent_when_all_selected_matchers_are_busy(
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
    metrics: list[dict] = []

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_preprocessors", pre_mock)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_postprocessors", post_mock)
    monkeypatch.setattr("nonebot.message.check_and_run_matcher", AsyncMock())
    monkeypatch.setattr(dispatch.nb_message.TrieRule, "get_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "mark_activity", lambda: None)
    monkeypatch.setattr(dispatch, "resolve_route_for_event", lambda _event: None)
    monkeypatch.setattr(dispatch, "event_command_traffic", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(dispatch, "select_priority_matchers", lambda priority_matchers, **_kwargs: priority_matchers)
    monkeypatch.setattr(dispatch, "record_group_message_ingress", lambda **kwargs: metrics.append(kwargs))
    monkeypatch.setattr(dispatch, "signal_overload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "overload_selected_threshold", lambda: 99)
    monkeypatch.setattr(dispatch, "matchers", {1: [BusyMatcher]})
    monkeypatch.setattr(dispatch_lanes, "lane_for_matcher", lambda _matcher: dispatch_lanes.DispatchLane.REMOTE)

    dispatch_lanes.install_dispatch_lanes()
    controller = dispatch_lanes.lane_controller(dispatch_lanes.DispatchLane.REMOTE)
    assert controller is not None
    for _ in range(controller.base_limit):
        ok, _ = await controller.acquire(0.01)
        assert ok is True

    await dispatch.patched_handle_event(bot, event)

    pre_mock.assert_awaited_once()
    post_mock.assert_awaited_once()
    assert len(metrics) == 1
    assert metrics[0]["matchers_run"] == 0

    for _ in range(controller.base_limit):
        await controller.release()
    dispatch_lanes.uninstall_dispatch_lanes()


@pytest.mark.asyncio
async def test_patched_handle_event_batches_selected_matchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGroupMessageEvent:
        raw_message = "foo"

        def get_log_string(self) -> str:
            return "fake group message"

        def get_plaintext(self) -> str:
            return "foo"

    class MatcherA:
        rule = Rule()

    class MatcherB:
        rule = Rule()

    class MatcherC:
        rule = Rule()

    class MatcherD:
        rule = Rule()

    class MatcherE:
        rule = Rule()

    bot = MagicMock()
    bot.type = "OneBot V11"
    bot.self_id = "10001"
    event = FakeGroupMessageEvent()
    pre_mock = AsyncMock(return_value=True)
    post_mock = AsyncMock()
    active = 0
    max_active = 0

    async def fake_run_selected_matcher(*_args, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        return dispatch_lanes.MatcherLaneResult(acquired=True, lane_busy=False)

    monkeypatch.setattr(dispatch, "GroupMessageEvent", FakeGroupMessageEvent)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_preprocessors", pre_mock)
    monkeypatch.setattr(dispatch.nb_message, "_apply_event_postprocessors", post_mock)
    monkeypatch.setattr(dispatch.nb_message.TrieRule, "get_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "mark_activity", lambda: None)
    monkeypatch.setattr(dispatch, "resolve_route_for_event", lambda _event: None)
    monkeypatch.setattr(dispatch, "event_command_traffic", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(dispatch, "select_priority_matchers", lambda priority_matchers, **_kwargs: priority_matchers)
    monkeypatch.setattr(dispatch, "record_group_message_ingress", lambda **_kwargs: None)
    monkeypatch.setattr(dispatch, "signal_overload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "overload_selected_threshold", lambda: 99)
    monkeypatch.setattr(
        dispatch,
        "repo_env_raw_value",
        lambda key: "2" if key == "PALLAS_MATCHER_DISPATCH_BATCH" else None,
    )
    monkeypatch.setattr(dispatch, "check_and_run_matcher_with_lane", fake_run_selected_matcher)
    monkeypatch.setattr(dispatch, "matchers", {1: [MatcherA, MatcherB, MatcherC, MatcherD, MatcherE]})

    await dispatch.patched_handle_event(bot, event)

    pre_mock.assert_awaited_once()
    post_mock.assert_awaited_once()
    assert max_active <= 2
