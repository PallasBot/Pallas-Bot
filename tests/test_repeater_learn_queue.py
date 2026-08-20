import asyncio

import pytest

from packages.repeater.learn_queue import learn_concurrency, learn_queue_max_size


def test_learn_defaults_reasonable():
    from packages.repeater.config import Config
    from packages.repeater.learn_runtime_config import RepeaterLearnRuntimeConfig

    assert Config.model_fields["learn_concurrency"].default == 8
    assert RepeaterLearnRuntimeConfig().learn_concurrency == 8
    assert learn_queue_max_size() >= 64


@pytest.mark.asyncio
async def test_learn_sem_limits_parallel(monkeypatch):
    from packages.repeater import learn_queue as lq

    monkeypatch.setattr(lq, "learn_concurrency", lambda: 2)
    lq.clear_repeater_learn_runtime_state()
    sem = lq.learn_sem()
    await sem.acquire()
    await sem.acquire()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sem.acquire(), timeout=0.05)
    sem.release()
    sem.release()


def test_learn_concurrency_caps_more_conservatively_for_write_heavy_queue(monkeypatch):
    from packages.repeater import learn_queue as lq

    monkeypatch.setattr(
        lq,
        "get_repeater_learn_runtime_config",
        lambda: type("Cfg", (), {"learn_concurrency": 24})(),
    )

    def fake_env(key: str):
        return {"PG_POOL_SIZE": "48", "PG_MAX_OVERFLOW": "24"}.get(key)

    monkeypatch.setattr(
        "pallas.core.foundation.db.pool_budget.repo_env_raw_value",
        fake_env,
    )
    from pallas.core.foundation.db.pool_budget import clear_pool_budget_runtime_cache

    clear_pool_budget_runtime_cache()

    assert learn_concurrency() == 2


def test_learn_concurrency_keeps_at_least_two_workers_on_small_pool(monkeypatch):
    from packages.repeater import learn_queue as lq

    monkeypatch.setattr(
        lq,
        "get_repeater_learn_runtime_config",
        lambda: type("Cfg", (), {"learn_concurrency": 24})(),
    )

    def fake_env(key: str):
        return {"PG_POOL_SIZE": "12", "PG_MAX_OVERFLOW": "8"}.get(key)

    monkeypatch.setattr(
        "pallas.core.foundation.db.pool_budget.repo_env_raw_value",
        fake_env,
    )
    from pallas.core.foundation.db.pool_budget import clear_pool_budget_runtime_cache

    clear_pool_budget_runtime_cache()

    assert learn_concurrency() == 2


def test_learn_queue_pressure_threshold_scales_with_queue_size(monkeypatch):
    from packages.repeater import learn_queue as lq

    monkeypatch.setattr(lq, "learn_queue_max_size", lambda: 200)
    assert lq.learn_queue_pressure_threshold() == 64

    monkeypatch.setattr(lq, "learn_queue_max_size", lambda: 2000)
    assert lq.learn_queue_pressure_threshold() == 125


def test_should_skip_repeater_learn_enqueue_prefers_pg_pressure(monkeypatch):
    from packages.repeater import learn_queue as lq

    monkeypatch.setattr(
        "pallas.core.foundation.db.pool_budget.pg_pool_under_pressure",
        lambda threshold=0.75: threshold <= 0.25,
    )
    monkeypatch.setattr(lq, "learn_queue_under_pressure", lambda: False)

    assert lq.should_skip_repeater_learn_enqueue() is True


def test_should_skip_repeater_learn_enqueue_uses_queue_pressure(monkeypatch):
    from packages.repeater import learn_queue as lq

    monkeypatch.setattr("pallas.core.foundation.db.pool_budget.pg_pool_under_pressure", lambda threshold=0.75: False)
    monkeypatch.setattr(lq, "learn_queue_under_pressure", lambda: True)

    assert lq.should_skip_repeater_learn_enqueue() is True


@pytest.mark.asyncio
async def test_wait_pg_pool_headroom_for_learn_uses_more_conservative_pressure_threshold(monkeypatch):
    from packages.repeater import learn_queue as lq

    seen: list[float] = []

    def fake_under_pressure(*, threshold: float = 0.75) -> bool:
        seen.append(threshold)
        return False

    monkeypatch.setattr("pallas.core.foundation.db.pool_budget.pg_pool_under_pressure", fake_under_pressure)

    await lq.wait_pg_pool_headroom_for_learn()

    assert seen == [0.25]


def _fake_group_event() -> object:
    return type(
        "Event",
        (),
        {"group_id": 1001, "message_id": "9001", "self_id": 9001, "user_id": 3001},
    )()


@pytest.mark.asyncio
async def test_message_queue_independent_from_learn_queue(monkeypatch):
    from packages.repeater import learn_queue as lq

    lq.clear_repeater_learn_runtime_state()
    mq = lq.message_queue()
    lq_ = lq.learn_queue()
    assert mq is not lq_
    assert mq.maxsize == lq_.maxsize


@pytest.mark.asyncio
async def test_message_persist_job_goes_to_message_queue(monkeypatch):
    from packages.repeater import learn_queue as lq

    lq.clear_repeater_learn_runtime_state()
    mq = lq.message_queue()
    lq_ = lq.learn_queue()
    ok = lq.enqueue_message_persist_job({"plain_text": "hi"}, _fake_group_event())
    assert ok is True
    assert mq.qsize() == 1
    assert lq_.qsize() == 0
    job = mq.get_nowait()
    assert job.kind == "repeater.message"
    assert job.payload["message"]["plain_text"] == "hi"
    mq.task_done()


@pytest.mark.asyncio
async def test_message_persist_uses_own_queue_when_learn_queue_full(monkeypatch):
    from packages.repeater import learn_queue as lq

    monkeypatch.setattr(lq, "learn_queue_max_size", lambda: 1)
    lq.clear_repeater_learn_runtime_state()
    lq_ = lq.learn_queue()
    mq = lq.message_queue()
    first = lq.WorkJob.create(kind="repeater.learn", payload={}, idempotency_key="x")
    await lq_.put(first)
    ok = lq.enqueue_message_persist_job({"plain_text": "still in"}, _fake_group_event())
    assert ok is True
    assert mq.qsize() == 1
    lq_.get_nowait()
    lq_.task_done()


@pytest.mark.asyncio
async def test_next_outbox_job_prefers_message_queue(monkeypatch):
    from packages.repeater import learn_queue as lq

    lq.clear_repeater_learn_runtime_state()
    mq = lq.message_queue()
    lq_ = lq.learn_queue()
    learn_job = lq.WorkJob.create(kind="repeater.learn", payload={}, idempotency_key="l")
    msg_job = lq.WorkJob.create(kind="repeater.message", payload={}, idempotency_key="m")
    await lq_.put(learn_job)
    await mq.put(msg_job)

    first = await lq._next_outbox_job()
    assert first is msg_job
    mq.task_done()
    second = await lq._next_outbox_job()
    assert second is learn_job
    lq_.task_done()
