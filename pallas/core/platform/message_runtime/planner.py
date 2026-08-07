from __future__ import annotations

from typing import TYPE_CHECKING

from .models import HandlingPlan, MessageContext

if TYPE_CHECKING:
    from .handlers import NativeHandlerRegistry


class MessagePlanner:
    def __init__(self, registry: NativeHandlerRegistry) -> None:
        self._registry = registry

    def plan(self, context: MessageContext) -> HandlingPlan:
        if not context.command_traffic:
            return HandlingPlan(kind="legacy", handler_ids=(), reason="chat_traffic")
        if len(context.route_modules) != 1:
            return HandlingPlan(
                kind="legacy",
                handler_ids=(),
                reason="ambiguous_route" if context.route_modules else "no_native_route",
            )
        handler_ids = self._registry.handler_ids_for_modules(context.route_modules)
        if len(handler_ids) != 1:
            return HandlingPlan(
                kind="legacy",
                handler_ids=(),
                reason="unique_route_unregistered" if not handler_ids else "multiple_native_handlers",
            )
        return HandlingPlan(kind="native", handler_ids=handler_ids, reason="unique_command")
