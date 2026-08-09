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
            exact_primary_handler_ids = self._registry.exact_passive_primary_handler_ids_for_context(context)
            if len(exact_primary_handler_ids) == 1:
                return HandlingPlan(
                    kind="native",
                    handler_ids=exact_primary_handler_ids,
                    reason="unique_exact_passive",
                )
            if len(exact_primary_handler_ids) > 1:
                return HandlingPlan(
                    kind="legacy",
                    handler_ids=(),
                    reason="multiple_exact_passive_primaries",
                )
            handler_ids = self._registry.passive_handler_ids_for_context(context)
            if len(handler_ids) == 1:
                return HandlingPlan(kind="native", handler_ids=handler_ids, reason="unique_passive")
            reason = "chat_traffic" if not handler_ids else "multiple_passive_handlers"
            return HandlingPlan(kind="legacy", handler_ids=(), reason=reason)
        if not context.route_modules:
            return HandlingPlan(kind="legacy", handler_ids=(), reason="no_native_route")
        handler_ids = self._registry.handler_ids_for_context(context)
        if not handler_ids:
            reason = "ambiguous_route" if len(context.route_modules) != 1 else "unique_route_unregistered"
            return HandlingPlan(kind="legacy", handler_ids=(), reason=reason)
        if len(handler_ids) != 1:
            return HandlingPlan(kind="legacy", handler_ids=(), reason="multiple_native_handlers")
        return HandlingPlan(kind="native", handler_ids=handler_ids, reason="unique_command")
