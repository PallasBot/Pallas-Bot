from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pallas.api.runtime import DirectBotAction, DirectWorkResult
from pallas.core.platform.work_jobs import bot_action_send
from pallas.core.platform.work_jobs.bot_action_send import handle_bot_action_send
from pallas.core.platform.work_jobs.result_committer import WorkResultCommitter
from pallas.core.platform.work_jobs.store import MemoryWorkJobStore


@pytest.mark.asyncio
async def test_send_handler_delegates_to_local_execute() -> None:
    with patch("pallas.core.platform.shard.coord.bot_action._execute_local", AsyncMock(return_value=(True, None))) as ex:
        result = await handle_bot_action_send(
            {"action": "send_group_msg", "bot_qq": 1001, "payload": {"group_id": 42, "message_text": "hi"}}
        )
    ex.assert_awaited_once_with("send_group_msg", 1001, {"group_id": 42, "message_text": "hi"})
    assert result is None


@pytest.mark.asyncio
async def test_send_handler_skips_invalid_payload() -> None:
    with patch("pallas.core.platform.shard.coord.bot_action._execute_local", AsyncMock()) as ex:
        assert await handle_bot_action_send({"action": "", "bot_qq": 0}) is None
        assert await handle_bot_action_send({"action": "send_group_msg", "bot_qq": "x"}) is None
        assert await handle_bot_action_send({"action": "send_group_msg", "bot_qq": 1001}) is None
    ex.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_handler_executes_job_payload_with_send_kind() -> None:
    store = MemoryWorkJobStore()
    committer = WorkResultCommitter(store=store)
    result = DirectWorkResult(actions=(DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "hi"}),))
    await committer.commit(result, job_kind="sing.submit", job_id="job-1")

    jobs = await store.claim_many(owner="tester", lease_sec=60, limit=4, kinds=frozenset({"bot_action.send"}))
    assert len(jobs) == 1
    with patch("pallas.core.platform.shard.coord.bot_action._execute_local", AsyncMock(return_value=(True, None))) as ex:
        await handle_bot_action_send(jobs[0].payload)
    ex.assert_awaited_once_with("send_group_msg", 1001, {"group_id": 42, "message_text": "hi"})
