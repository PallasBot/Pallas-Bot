from __future__ import annotations

from nonebot import logger

from .handlers import RuntimeHandlerRegistry
from .planner import MessagePlanner
from .runtime import MessageRuntime

_direct_runtime: MessageRuntime | None = None


def configure_direct_runtime() -> None:
    global _direct_runtime
    registry = RuntimeHandlerRegistry()
    from packages.drink.direct import DrinkDirectHandler
    from packages.greeting.direct import CallMeDirectHandler
    from packages.help.direct import HelpDirectHandler
    from packages.llm_chat.message_runtime_handler import LlmChatDirectHandler
    from packages.pb_core.direct import ConsoleDirectHandler, PluginsDirectHandler, StatusDirectHandler
    from packages.repeater.message_runtime_handler import RepeaterDirectHandler

    registry.register(DrinkDirectHandler())
    registry.register(CallMeDirectHandler())
    registry.register(HelpDirectHandler())
    registry.register(StatusDirectHandler())
    registry.register(ConsoleDirectHandler())
    registry.register(PluginsDirectHandler())
    registry.register(RepeaterDirectHandler())
    registry.register(LlmChatDirectHandler())
    from .declarations import build_declaration_handlers

    declaration_handlers, diagnostics = build_declaration_handlers()
    for handler in declaration_handlers:
        registry.register(handler)
    for diagnostic in diagnostics:
        logger.warning(
            "MessageRuntime direct registration skipped code={} handler_id={} module={} commands={}",
            diagnostic.code,
            diagnostic.handler_id,
            diagnostic.module,
            diagnostic.commands,
        )
    _direct_runtime = MessageRuntime(MessagePlanner(registry), registry)


def direct_runtime_for_group(_group_id: int) -> MessageRuntime | None:
    return _direct_runtime


def reset_direct_runtime_for_tests() -> None:
    global _direct_runtime
    _direct_runtime = None
