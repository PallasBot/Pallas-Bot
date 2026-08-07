from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .models import HandlingOutcome, MessageContext


class NativeHandler(Protocol):
    handler_id: str
    modules: frozenset[str]

    async def handle(self, context: MessageContext) -> HandlingOutcome: ...


class NativeHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, NativeHandler] = {}
        self._module_handlers: dict[str, set[str]] = {}

    def register(self, handler: NativeHandler) -> None:
        if handler.handler_id in self._handlers:
            raise ValueError(f"duplicate native handler: {handler.handler_id}")
        self._handlers[handler.handler_id] = handler
        for module in handler.modules:
            self._module_handlers.setdefault(module, set()).add(handler.handler_id)

    def handler_ids_for_modules(self, modules: frozenset[str]) -> tuple[str, ...]:
        handler_ids = {handler_id for module in modules for handler_id in self._module_handlers.get(module, ())}
        return tuple(sorted(handler_ids))

    def get(self, handler_id: str) -> NativeHandler | None:
        return self._handlers.get(handler_id)
