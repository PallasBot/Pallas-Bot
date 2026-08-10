from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.core.platform.message_runtime.committer import ActionCommitter, SideEffectCommitError
from pallas.core.platform.message_runtime.models import (
    CrossWorkerAction,
    DeferredAction,
    HandlingOutcome,
    SendAction,
)
from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.store import MemoryWorkJobStore


@pytest.mark.asyncio
async def test_committer_enqueues_work_before_sending_actions() -> None:
    store = MemoryWorkJobStore()
    bot = type("Bot", (), {"send": AsyncMock()})()
    job = WorkJob.create(kind="repeater.learn", payload={"message_id": 3}, idempotency_key="repeater.learn:3")
    outcome = HandlingOutcome(handled=True, actions=(SendAction("reply"),), work_jobs=(job,))

    committed = await ActionCommitter(lambda: store).commit(outcome, bot=bot, event="event")

    assert committed is True
    bot.send.assert_awaited_once_with("event", "reply")
    assert (await store.stats())["pending"] == 1


@pytest.mark.asyncio
async def test_committer_marks_failed_work_submission_as_side_effect_started() -> None:
    store = type("Store", (), {"enqueue_many": AsyncMock(side_effect=RuntimeError("db unavailable"))})()
    job = WorkJob.create(kind="repeater.learn", payload={"message_id": 3}, idempotency_key="repeater.learn:3")

    with pytest.raises(SideEffectCommitError) as raised:
        await ActionCommitter(lambda: store).commit(
            HandlingOutcome(handled=True, work_jobs=(job,)),
            bot=object(),
            event=object(),
        )

    assert raised.value.committed is True


@pytest.mark.asyncio
async def test_committer_schedules_deferred_actions_and_dispatches_cross_worker_actions(monkeypatch) -> None:
    from pallas.core.platform.message_runtime import committer as module

    scheduled: list[str | None] = []
    dispatched: list[CrossWorkerAction] = []

    def fake_create_task(coro, *, name=None):
        scheduled.append(name)
        coro.close()
        return object()

    async def fake_dispatch(action: CrossWorkerAction) -> None:
        dispatched.append(action)

    monkeypatch.setattr(module.asyncio, "create_task", fake_create_task)
    committer = ActionCommitter(lambda: MemoryWorkJobStore(), cross_worker_dispatcher=fake_dispatch)
    outcome = HandlingOutcome(
        handled=True,
        deferred_actions=(DeferredAction(name="repeater_reply_1_2", run=lambda: asyncio.sleep(0)),),
        cross_worker_actions=(
            CrossWorkerAction(
                kind="repeater.fanout_reply",
                target_bot_id=3,
                payload={"group_id": 2},
                idempotency_key="repeater.fanout:2:3",
            ),
        ),
    )

    assert await committer.commit(outcome, bot=object(), event=object()) is True
    assert scheduled == ["repeater_reply_1_2"]
    assert dispatched == list(outcome.cross_worker_actions)


@pytest.mark.asyncio
async def test_committer_waits_for_required_deferred_action_and_reports_failure() -> None:
    async def fail() -> None:
        raise RuntimeError("state mutation failed")

    outcome = HandlingOutcome(
        handled=True,
        deferred_actions=(
            DeferredAction(
                name="drink_1_2",
                run=fail,
                wait_for_completion=True,
            ),
        ),
    )

    with pytest.raises(SideEffectCommitError, match="direct deferred action failed"):
        await ActionCommitter(lambda: MagicMock()).commit(outcome, bot=MagicMock(), event=MagicMock())


@pytest.mark.asyncio
async def test_cross_worker_dispatcher_rejects_unknown_action() -> None:
    from pallas.core.platform.message_runtime.committer import dispatch_cross_worker_action

    with pytest.raises(ValueError, match="unsupported"):
        await dispatch_cross_worker_action(
            CrossWorkerAction(
                kind="unknown.action",
                target_bot_id=3,
                payload={},
                idempotency_key="unknown:3",
            )
        )
