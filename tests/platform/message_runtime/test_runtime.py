from __future__ import annotations

import pytest

from pallas.core.platform.message_runtime.handlers import NativeHandlerRegistry
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext, RuntimeMode
from pallas.core.platform.message_runtime.planner import MessagePlanner
from pallas.core.platform.message_runtime.runtime import MessageRuntime


class StatusHandler:
    handler_id = "pb_core.status"
    modules = frozenset({"pb_core"})

    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, context: MessageContext, *, bot: object, event: object) -> HandlingOutcome:
        self.calls += 1
        return HandlingOutcome(handled=True)


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
