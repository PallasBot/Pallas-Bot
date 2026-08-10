from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event

    from .models import HandlingOutcome, MessageContext


class RuntimeHandler(Protocol):
    handler_id: str
    modules: frozenset[str]
    passive: bool

    def accepts(self, context: MessageContext) -> bool: ...

    async def handle(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome: ...


class RuntimeHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, RuntimeHandler] = {}
        self._module_handlers: dict[str, set[str]] = {}

    def register(self, handler: RuntimeHandler) -> None:
        if handler.handler_id in self._handlers:
            raise ValueError(f"duplicate runtime handler: {handler.handler_id}")
        self._handlers[handler.handler_id] = handler
        for module in handler.modules:
            self._module_handlers.setdefault(module, set()).add(handler.handler_id)

    def handler_ids_for_context(self, context: MessageContext) -> tuple[str, ...]:
        handler_ids = {
            handler_id
            for module in context.route_modules
            for handler_id in self._module_handlers.get(module, ())
            if self._handlers[handler_id].accepts(context)
        }
        return tuple(sorted(handler_ids))

    def passive_handler_ids_for_context(self, context: MessageContext) -> tuple[str, ...]:
        return tuple(
            sorted(
                handler_id
                for handler_id, handler in self._handlers.items()
                if getattr(handler, "passive", False) and handler.accepts(context)
            )
        )

    def exact_passive_primary_handler_ids_for_context(self, context: MessageContext) -> tuple[str, ...]:
        return tuple(
            sorted(
                handler_id
                for handler_id, handler in self._handlers.items()
                if getattr(handler, "passive", False)
                and getattr(handler, "exact_passive_primary", False)
                and handler.accepts(context)
            )
        )

    def get(self, handler_id: str) -> RuntimeHandler | None:
        return self._handlers.get(handler_id)
