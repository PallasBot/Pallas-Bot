from __future__ import annotations

from pallas.core.platform.message_runtime.handlers import NativeHandlerRegistry
from pallas.core.platform.message_runtime.models import HandlingOutcome, MessageContext
from pallas.core.platform.message_runtime.planner import MessagePlanner


class StatusHandler:
    handler_id = "pb_core.status"
    modules = frozenset({"pb_core"})

    def __init__(self, accepted: str = "#pallas", handler_id: str = "pb_core.status") -> None:
        self.calls = 0
        self.accepted = accepted
        self.handler_id = handler_id

    def accepts(self, context: MessageContext) -> bool:
        return context.plain_text == self.accepted

    async def handle(self, context: MessageContext) -> HandlingOutcome:
        self.calls += 1
        return HandlingOutcome(handled=True)


class PassiveHandler(StatusHandler):
    handler_id = "repeater.message"
    passive = True

    def accepts(self, context: MessageContext) -> bool:
        return not context.is_to_me


def _context(*, route_modules: set[str], command_traffic: bool = True, plain_text: str = "#pallas") -> MessageContext:
    return MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text=plain_text,
        raw_text=plain_text,
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
    registry.register(StatusHandler(handler_id="help.status"))
    planner = MessagePlanner(registry)

    assert planner.plan(_context(route_modules={"pb_core", "help"})).reason == "multiple_native_handlers"
    assert planner.plan(_context(route_modules={"pb_core"}, command_traffic=False)).reason == "chat_traffic"


def test_planner_selects_a_single_registered_passive_handler() -> None:
    registry = NativeHandlerRegistry()
    registry.register(PassiveHandler(handler_id="repeater.message"))

    plan = MessagePlanner(registry).plan(_context(route_modules=set(), command_traffic=False, plain_text="闲聊"))

    assert plan.kind == "native"
    assert plan.handler_ids == ("repeater.message",)
    assert plan.reason == "unique_passive"


def test_planning_never_invokes_a_registered_handler() -> None:
    handler = StatusHandler()
    registry = NativeHandlerRegistry()
    registry.register(handler)

    MessagePlanner(registry).plan(_context(route_modules={"pb_core"}))

    assert handler.calls == 0


def test_planner_selects_the_exact_command_within_one_module() -> None:
    registry = NativeHandlerRegistry()
    registry.register(StatusHandler())
    registry.register(StatusHandler("牛牛控制台", "pb_core.console"))
    planner = MessagePlanner(registry)

    plan = planner.plan(_context(route_modules={"pb_core"}, plain_text="牛牛控制台"))

    assert plan.handler_ids == ("pb_core.console",)


def test_planner_selects_help_toggle_despite_unhandled_route_module() -> None:
    from packages.help.native import HelpNativeHandler

    registry = NativeHandlerRegistry()
    registry.register(HelpNativeHandler())

    plan = MessagePlanner(registry).plan(
        _context(
            route_modules={"help", "request_handler"},
            plain_text="牛牛开启 sing",
        )
    )

    assert plan.kind == "native"
    assert plan.handler_ids == ("help.commands",)
