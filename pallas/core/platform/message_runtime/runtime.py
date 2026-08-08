from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.core.platform.work_jobs.runtime import build_work_job_store

from .committer import ActionCommitter, SideEffectCommitError
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
        action_committer: ActionCommitter | None = None,
    ) -> None:
        self._mode = mode
        self._planner = planner
        self._registry = registry
        self._action_committer = action_committer or ActionCommitter(build_work_job_store)

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
            if not getattr(handler, "fallback_on_error", True):
                return HandlingOutcome(handled=True, error_class=error_class)
            return HandlingOutcome(handled=False, fallback_to_legacy=True, error_class=error_class)

    async def execute_and_commit(self, context: MessageContext, *, bot: Bot, event: Event) -> HandlingOutcome:
        outcome = await self.execute(context, bot=bot, event=event)
        if outcome.handled and not outcome.fallback_to_legacy:
            try:
                await self._action_committer.commit(outcome, bot=bot, event=event)
            except SideEffectCommitError as exc:
                logger.warning("MessageRuntime native side effect failed error_class={}", type(exc).__name__)
                return replace(outcome, error_class=type(exc).__name__)
        return outcome
