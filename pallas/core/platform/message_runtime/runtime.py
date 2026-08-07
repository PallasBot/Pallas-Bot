from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .handlers import NativeHandlerRegistry
    from .models import HandlingPlan, MessageContext, RuntimeMode
    from .planner import MessagePlanner


class MessageRuntime:
    def __init__(
        self,
        mode: RuntimeMode,
        planner: MessagePlanner,
        registry: NativeHandlerRegistry,
    ) -> None:
        self._mode = mode
        self._planner = planner
        self._registry = registry

    async def submit(self, context: MessageContext) -> HandlingPlan:
        return self._planner.plan(context)
