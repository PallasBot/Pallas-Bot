from __future__ import annotations

import pytest


def test_work_job_normalizes_a_repeater_learn_payload() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob

    job = WorkJob.create(
        kind="repeater.learn",
        payload={"chat": {"group_id": 10086, "raw_message": "hello"}},
        idempotency_key="repeater.learn:10086:123",
    )

    assert job.kind == "repeater.learn"
    assert job.payload == {"chat": {"group_id": 10086, "raw_message": "hello"}}
    assert job.idempotency_key == "repeater.learn:10086:123"
    assert job.attempts == 0


def test_work_job_rejects_an_empty_kind_or_idempotency_key() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob

    with pytest.raises(ValueError, match="kind"):
        WorkJob.create(kind="", payload={}, idempotency_key="job:1")
    with pytest.raises(ValueError, match="idempotency"):
        WorkJob.create(kind="repeater.learn", payload={}, idempotency_key=" ")
