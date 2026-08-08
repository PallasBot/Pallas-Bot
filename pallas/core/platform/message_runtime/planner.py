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
        if not context.route_modules:
            return HandlingPlan(kind="legacy", handler_ids=(), reason="no_native_route")
        handler_ids = self._registry.handler_ids_for_context(context)
        if not handler_ids:
            reason = "ambiguous_route" if len(context.route_modules) != 1 else "unique_route_unregistered"
            return HandlingPlan(kind="legacy", handler_ids=(), reason=reason)
        if len(handler_ids) != 1:
            return HandlingPlan(kind="legacy", handler_ids=(), reason="multiple_native_handlers")
        return HandlingPlan(kind="native", handler_ids=handler_ids, reason="unique_command")
