from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.core.platform.message_runtime.committer import ActionCommitter, SideEffectCommitError
from pallas.core.platform.message_runtime.models import HandlingOutcome, SendAction
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
