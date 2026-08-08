from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters import Bot, Event

    from pallas.core.platform.work_jobs.store import WorkJobStore

    from .models import HandlingOutcome


class SideEffectCommitError(RuntimeError):
    """A native side effect may have been accepted, so legacy cannot retry."""

    committed = True


class ActionCommitter:
    def __init__(self, work_job_store: Callable[[], WorkJobStore]) -> None:
        self._work_job_store = work_job_store

    async def commit(self, outcome: HandlingOutcome, *, bot: Bot, event: Event) -> bool:
        if outcome.fallback_to_legacy:
            raise ValueError("fallback outcomes cannot be committed")
        if not outcome.actions and not outcome.work_jobs:
            return False
        if outcome.work_jobs:
            try:
                await self._work_job_store().enqueue_many(list(outcome.work_jobs))
            except Exception as exc:
                raise SideEffectCommitError("native work submission failed") from exc
        for action in outcome.actions:
            try:
                await bot.send(event, action.message)
            except Exception as exc:
                raise SideEffectCommitError("native action submission failed") from exc
        return True
