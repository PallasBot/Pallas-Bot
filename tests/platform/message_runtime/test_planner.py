from __future__ import annotations

from pallas.core.platform.message_runtime.handlers import NativeHandlerRegistry
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext
from pallas.core.platform.message_runtime.planner import MessagePlanner


class StatusHandler:
    handler_id = "pb_core.status"
    modules = frozenset({"pb_core"})

    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, context: MessageContext) -> HandlingOutcome:
        self.calls += 1
        return HandlingOutcome(handled=True)


def _context(*, route_modules: set[str], command_traffic: bool = True) -> MessageContext:
    return MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text="#pallas",
        raw_text="#pallas",
        is_to_me=False,
        command_traffic=command_traffic,
        route_modules=frozenset(route_modules),
    )


def test_planner_selects_a_single_registered_command_handler() -> None:
    registry = NativeHandlerRegistry()
    registry.register(StatusHandler())

    plan = MessagePlanner(registry).plan(_context(route_modules={"pb_core"}))

    assert plan.kind == "native"
    assert plan.handler_ids == ("pb_core.status",)
    assert plan.reason == "unique_command"


def test_planner_sends_ambiguous_and_chat_traffic_to_legacy() -> None:
    registry = NativeHandlerRegistry()
    registry.register(StatusHandler())
    planner = MessagePlanner(registry)

    assert planner.plan(_context(route_modules={"pb_core", "help"})).reason == "ambiguous_route"
    assert planner.plan(_context(route_modules={"pb_core"}, command_traffic=False)).reason == "chat_traffic"


def test_planning_never_invokes_a_registered_handler() -> None:
    handler = StatusHandler()
    registry = NativeHandlerRegistry()
    registry.register(handler)

    MessagePlanner(registry).plan(_context(route_modules={"pb_core"}))

    assert handler.calls == 0
