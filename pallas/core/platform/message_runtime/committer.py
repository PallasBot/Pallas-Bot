from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from nonebot.adapters import Bot, Event

    from pallas.core.platform.work_jobs.store import WorkJobStore

    from .models import CrossWorkerAction, HandlingOutcome


class SideEffectCommitError(RuntimeError):
    """A native side effect may have been accepted, so legacy cannot retry."""

    committed = True


async def dispatch_cross_worker_action(action: CrossWorkerAction) -> None:
    if action.kind != "repeater.fanout_reply":
        raise ValueError(f"unsupported cross-worker action: {action.kind}")
    from pallas.core.platform.shard.coord.bot_action import invoke_bot_action

    payload = dict(action.payload)
    ok, _result = await invoke_bot_action(
        "repeater_fanout_reply",
        action.target_bot_id,
        payload,
        timeout_sec=action.timeout_sec,
    )
    if not ok:
        raise RuntimeError("cross-worker action was not accepted")


class ActionCommitter:
    def __init__(
        self,
        work_job_store: Callable[[], WorkJobStore],
        *,
        cross_worker_dispatcher: Callable[[CrossWorkerAction], Awaitable[None]] = dispatch_cross_worker_action,
    ) -> None:
        self._work_job_store = work_job_store
        self._cross_worker_dispatcher = cross_worker_dispatcher

    async def commit(self, outcome: HandlingOutcome, *, bot: Bot, event: Event) -> bool:
        if outcome.fallback_to_legacy:
            raise ValueError("fallback outcomes cannot be committed")
        if not (outcome.actions or outcome.work_jobs or outcome.deferred_actions or outcome.cross_worker_actions):
            return False
        if outcome.work_jobs:
            try:
                await self._work_job_store().enqueue_many(list(outcome.work_jobs))
            except Exception as exc:
                raise SideEffectCommitError("native work submission failed") from exc
        for action in outcome.cross_worker_actions:
            try:
                await self._cross_worker_dispatcher(action)
            except Exception as exc:
                raise SideEffectCommitError("native cross-worker action submission failed") from exc
        for action in outcome.actions:
            try:
                await bot.send(event, action.message)
            except Exception as exc:
                raise SideEffectCommitError("native action submission failed") from exc
        for action in outcome.deferred_actions:
            try:
                asyncio.create_task(action.run(), name=action.name)
            except Exception as exc:
                raise SideEffectCommitError("native deferred action submission failed") from exc
        return True
