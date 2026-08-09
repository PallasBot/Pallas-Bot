from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.core.platform.message_runtime.handlers import NativeHandlerRegistry
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext, RuntimeMode, SendAction
from pallas.core.platform.message_runtime.planner import MessagePlanner
from pallas.core.platform.message_runtime.runtime import MessageRuntime


class StatusHandler:
    handler_id = "pb_core.status"
    modules = frozenset({"pb_core"})

    def __init__(self) -> None:
        self.calls = 0

    def accepts(self, context: MessageContext) -> bool:
        return context.plain_text == "#pallas"

    async def handle(self, context: MessageContext, *, bot: object, event: object) -> HandlingOutcome:
        self.calls += 1
        return HandlingOutcome(handled=True)


class RaisingHandler(StatusHandler):
    handler_id = "pb_core.raising"

    async def handle(self, context: MessageContext, *, bot: object, event: object) -> HandlingOutcome:
        raise RuntimeError("secret command body")


class SendingHandler(StatusHandler):
    handler_id = "pb_core.sending"

    async def handle(self, context: MessageContext, *, bot: object, event: object) -> HandlingOutcome:
        return HandlingOutcome(handled=True, actions=(SendAction("reply"),))


class SideEffectingHandler(StatusHandler):
    handler_id = "repeater.message"
    fallback_on_error = False

    async def handle(self, context: MessageContext, *, bot: object, event: object) -> HandlingOutcome:
        raise RuntimeError("producer failed")


class PassiveLegacyBridgeHandler(StatusHandler):
    handler_id = "repeater.message"
    fallback_on_error = True

    async def handle(self, context: MessageContext, *, bot: object, event: object) -> HandlingOutcome:
        return HandlingOutcome(handled=False, fallback_to_legacy=True)


def _context() -> MessageContext:
    return MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="#pallas",
        raw_text="#pallas",
        is_to_me=False,
        command_traffic=True,
        route_modules=frozenset({"pb_core"}),
    )


@pytest.mark.asyncio
async def test_shadow_runtime_plans_without_executing_native_handler() -> None:
    handler = StatusHandler()
    registry = NativeHandlerRegistry()
    registry.register(handler)
    runtime = MessageRuntime(RuntimeMode.SHADOW, MessagePlanner(registry), registry)

    plan = await runtime.submit(_context())

    assert plan.kind == "native"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_native_runtime_executes_the_planned_handler() -> None:
    handler = StatusHandler()
    registry = NativeHandlerRegistry()
    registry.register(handler)
    runtime = MessageRuntime(RuntimeMode.NATIVE, MessagePlanner(registry), registry)

    outcome = await runtime.execute(_context(), bot=object(), event=object())

    assert outcome == HandlingOutcome(handled=True)
    assert handler.calls == 1


@pytest.mark.asyncio
async def test_native_runtime_commits_actions_centrally() -> None:
    registry = NativeHandlerRegistry()
    registry.register(SendingHandler())
    bot = type("Bot", (), {"send": AsyncMock()})()

    outcome = await MessageRuntime(RuntimeMode.NATIVE, MessagePlanner(registry), registry).execute_and_commit(
        _context(), bot=bot, event="event"
    )

    assert outcome == HandlingOutcome(handled=True, actions=(SendAction("reply"),))
    bot.send.assert_awaited_once_with("event", "reply")


@pytest.mark.asyncio
async def test_native_runtime_does_not_fallback_after_action_submission_fails() -> None:
    registry = NativeHandlerRegistry()
    registry.register(SendingHandler())
    bot = type("Bot", (), {"send": AsyncMock(side_effect=RuntimeError("transport failed"))})()

    outcome = await MessageRuntime(RuntimeMode.NATIVE, MessagePlanner(registry), registry).execute_and_commit(
        _context(), bot=bot, event="event"
    )

    assert outcome.handled is True
    assert outcome.fallback_to_legacy is False
    assert outcome.error_class == "SideEffectCommitError"


@pytest.mark.asyncio
async def test_native_fallback_does_not_commit_or_retry_native_side_effects() -> None:
    registry = NativeHandlerRegistry()
    registry.register(PassiveLegacyBridgeHandler())
    committer = type("Committer", (), {"commit": AsyncMock()})()
    runtime = MessageRuntime(
        RuntimeMode.NATIVE,
        MessagePlanner(registry),
        registry,
        action_committer=committer,
    )

    outcome = await runtime.execute_and_commit(_context(), bot=object(), event=object())

    assert outcome == HandlingOutcome(handled=False, fallback_to_legacy=True)
    committer.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_handler_error_is_classified_without_logging_message_content(monkeypatch) -> None:
    from pallas.core.platform.message_runtime import runtime as runtime_module

    registry = NativeHandlerRegistry()
    registry.register(RaisingHandler())
    logger = MagicMock()
    monkeypatch.setattr(runtime_module, "logger", logger)

    outcome = await MessageRuntime(RuntimeMode.NATIVE, MessagePlanner(registry), registry).execute(
        _context(), bot=object(), event=object()
    )

    assert outcome == HandlingOutcome(
        handled=False,
        fallback_to_legacy=True,
        error_class="RuntimeError",
    )
    logger.warning.assert_called_once_with(
        "MessageRuntime native handler failed handler_id={} error_class={}",
        "pb_core.raising",
        "RuntimeError",
    )


@pytest.mark.asyncio
async def test_passive_legacy_bridge_does_not_suppress_legacy_matchers() -> None:
    registry = NativeHandlerRegistry()
    registry.register(PassiveLegacyBridgeHandler())
    context = MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="聊天",
        raw_text="聊天",
        is_to_me=False,
        command_traffic=False,
        route_modules=frozenset(),
    )

    outcome = await MessageRuntime(RuntimeMode.NATIVE, MessagePlanner(registry), registry).execute(
        context, bot=object(), event=object()
    )

    assert outcome == HandlingOutcome(handled=False, fallback_to_legacy=True)


@pytest.mark.asyncio
async def test_side_effecting_native_handler_error_does_not_fallback_to_legacy() -> None:
    registry = NativeHandlerRegistry()
    registry.register(SideEffectingHandler())

    outcome = await MessageRuntime(RuntimeMode.NATIVE, MessagePlanner(registry), registry).execute(
        _context(), bot=object(), event=object()
    )

    assert outcome.handled is True
    assert outcome.fallback_to_legacy is False
    assert outcome.error_class == "RuntimeError"
