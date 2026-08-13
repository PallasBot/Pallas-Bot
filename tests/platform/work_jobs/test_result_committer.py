from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.api.runtime import DirectBotAction, DirectWorkResult
from pallas.core.platform.work_jobs.result_committer import (
    SEND_JOB_KIND,
    WorkResultCommitError,
    WorkResultCommitter,
)
from pallas.core.platform.work_jobs.store import MemoryWorkJobStore


async def _collect_claims(store: MemoryWorkJobStore) -> list[dict]:
    jobs = await store.claim_many(owner="tester", lease_sec=60, limit=16, kinds=frozenset({SEND_JOB_KIND}))
    return [dict(job.payload) for job in jobs]


@pytest.mark.asyncio
async def test_result_committer_enqueues_send_tasks_in_order() -> None:
    store = MemoryWorkJobStore()
    committer = WorkResultCommitter(store=store)
    result = DirectWorkResult(
        actions=(
            DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "first"}, 10),
            DirectBotAction("send_private_msg", 1001, {"user_id": 7, "message_text": "second"}, 20),
        )
    )

    assert await committer.commit(result, job_kind="sing.submit", job_id="job-1") is True
    claims = await _collect_claims(store)
    assert [c["action"] for c in claims] == ["send_group_msg", "send_private_msg"]
    assert claims[0]["bot_qq"] == 1001
    assert claims[0]["payload"] == {"group_id": 42, "message_text": "first"}
    assert claims[0]["timeout_sec"] == 10


@pytest.mark.asyncio
async def test_result_committer_reports_no_work_for_an_empty_result() -> None:
    store = MemoryWorkJobStore()
    committer = WorkResultCommitter(store=store)

    assert await committer.commit(DirectWorkResult()) is False
    assert await _collect_claims(store) == []


@pytest.mark.asyncio
async def test_result_committer_revalidates_mutated_action_before_enqueue() -> None:
    store = MemoryWorkJobStore()
    committer = WorkResultCommitter(store=store)
    action = DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "hello"})
    action.payload["group_id"] = 0

    with pytest.raises(WorkResultCommitError, match="group_id must be positive"):
        await committer.commit(DirectWorkResult(actions=(action,)))

    assert await _collect_claims(store) == []


@pytest.mark.asyncio
async def test_result_committer_warns_when_action_invalid_with_job_context(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(
        "pallas.core.platform.work_jobs.result_committer.logger",
        SimpleNamespace(warning=lambda message, *args: warnings.append((message, args))),
    )
    store = MemoryWorkJobStore()
    committer = WorkResultCommitter(store=store)
    action = DirectBotAction("send_group_msg", 1001, {"group_id": 42, "message_text": "hello"})
    action.payload["group_id"] = 0

    with pytest.raises(WorkResultCommitError, match="group_id must be positive"):
        await committer.commit(DirectWorkResult(actions=(action,)), job_kind="repeater.learn", job_id="abc123")

    assert len(warnings) == 1
    message, args = warnings[0]
    assert message == (
        "work aux: result action [{}] for bot [{}] is invalid while committing job [{}] of kind [{}]: {}"
    )
    assert args[:4] == ("send_group_msg", 1001, "abc123", "repeater.learn")
    assert str(args[4]) == "group_id must be positive"
