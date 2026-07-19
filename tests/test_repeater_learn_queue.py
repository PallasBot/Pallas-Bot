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
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        fake_env,
    )

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
