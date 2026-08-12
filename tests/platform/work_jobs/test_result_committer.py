from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from pallas.api.runtime import DirectBotAction, DirectWorkResult
from pallas.core.platform.work_jobs.result_committer import WorkResultCommitError, WorkResultCommitter


@pytest.mark.asyncio
async def test_result_committer_dispatches_actions_in_order() -> None:
    dispatch = AsyncMock(side_effect=[(True, {"message_id": 1}), (True, None)])
    committer = WorkResultCommitter(dispatcher=dispatch)
    result = DirectWorkResult(
        actions=(
            DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "first"}, 10),
            DirectBotAction("send_private_msg", 1001, {"user_id": 7, "message_text": "second"}, 20),
        )
    )

    assert await committer.commit(result) is True
    assert dispatch.await_args_list == [
        call("send_group_msg", 1001, {"group_id": 42, "message_text": "first"}, timeout_sec=10),
        call("send_private_msg", 1001, {"user_id": 7, "message_text": "second"}, timeout_sec=20),
    ]


@pytest.mark.asyncio
async def test_result_committer_raises_when_an_action_is_not_accepted() -> None:
    dispatch = AsyncMock(return_value=(False, None))
    committer = WorkResultCommitter(dispatcher=dispatch)
    result = DirectWorkResult(
        actions=(DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "hello"}),)
    )

    with pytest.raises(WorkResultCommitError, match="was not accepted"):
        await committer.commit(result)


@pytest.mark.asyncio
async def test_result_committer_reports_no_work_for_an_empty_result() -> None:
    dispatch = AsyncMock()

    assert await WorkResultCommitter(dispatcher=dispatch).commit(DirectWorkResult()) is False
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_result_committer_revalidates_mutated_action_before_dispatch() -> None:
    dispatch = AsyncMock(return_value=(True, None))
    action = DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "hello"})
    action.payload["group_id"] = 0

    with pytest.raises(WorkResultCommitError, match="group_id must be positive"):
        await WorkResultCommitter(dispatcher=dispatch).commit(DirectWorkResult(actions=(action,)))

    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_result_committer_warns_when_action_rejected_with_job_context(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(
        "pallas.core.platform.work_jobs.result_committer.logger",
        SimpleNamespace(warning=lambda message, *args: warnings.append((message, args))),
    )
    dispatch = AsyncMock(return_value=(False, None))
    committer = WorkResultCommitter(dispatcher=dispatch)
    result = DirectWorkResult(
        actions=(DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "hello"}),)
    )

    with pytest.raises(WorkResultCommitError, match="was not accepted"):
        await committer.commit(result, job_kind="repeater.learn", job_id="abc123")

    assert warnings == [
        (
            "work aux: result action [{}] for bot [{}] was not accepted while committing job [{}] of kind [{}]",
            ("send_group_msg", 1001, "abc123", "repeater.learn"),
        )
    ]
