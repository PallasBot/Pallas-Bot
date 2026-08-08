from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger

from .models import HandlingOutcome

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event

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

    async def execute(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        plan = self._planner.plan(context)
        if plan.kind != "native" or len(plan.handler_ids) != 1:
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        handler = self._registry.get(plan.handler_ids[0])
        if handler is None:
            return HandlingOutcome(handled=False, fallback_to_legacy=True)
        try:
            return await handler.handle(context, bot=bot, event=event)
        except Exception as exc:
            error_class = type(exc).__name__
            logger.warning(
                "MessageRuntime native handler failed handler_id={} error_class={}",
                handler.handler_id,
                error_class,
            )
            return HandlingOutcome(
                handled=False,
                fallback_to_legacy=True,
                error_class=error_class,
            )
