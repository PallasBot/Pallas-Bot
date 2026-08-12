from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from pallas.core.platform.ingress import cold_start as mod
from pallas.core.platform.ingress import conversation_scheduler as sched_mod
from pallas.core.platform.ingress.conversation_scheduler import ConversationScheduler


class _FakeEvent:
    def __init__(self, t: float) -> None:
        self.time = t


def test_ingress_uptime_before_ready_is_infinite() -> None:
    mod._ready_at = None
    assert mod.ingress_uptime_sec() == float("inf")


def test_mark_ingress_ready_starts_uptime() -> None:
    mod._ready_at = None
    mod.mark_ingress_ready()
    assert mod.ingress_uptime_sec() < 1.0


def test_message_age_sec_uses_event_time() -> None:
    event = _FakeEvent(time.time() - 120.0)
    assert mod.message_age_sec(event) == pytest.approx(120.0, abs=1.0)
    assert mod.message_age_sec(_FakeEvent(0)) == 0.0
    assert mod.message_age_sec(_FakeEvent(None)) == 0.0


def test_stale_message_drop_needed_respects_threshold(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.dispatch_runtime_config.get_ingress_dispatch_runtime_config",
        lambda: SimpleNamespace(stale_message_sec=120.0),
    )
    assert mod.stale_message_drop_needed(_FakeEvent(time.time() - 200.0)) is True
    assert mod.stale_message_drop_needed(_FakeEvent(time.time() - 10.0)) is False


def test_stale_message_drop_disabled_when_threshold_zero(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.dispatch_runtime_config.get_ingress_dispatch_runtime_config",
        lambda: SimpleNamespace(stale_message_sec=0.0),
    )
    assert mod.stale_message_drop_needed(_FakeEvent(time.time() - 1000.0)) is False


@pytest.mark.asyncio
async def test_startup_ramp_gradually_reaches_target(monkeypatch) -> None:
    config = SimpleNamespace(
        conversation_scheduler_concurrency=8,
        conversation_scheduler_startup_concurrency=2,
        conversation_scheduler_adaptive_interval_sec=0.01,
        conversation_scheduler_llm_reserved=6,
    )
    monkeypatch.setattr(sched_mod, "get_ingress_dispatch_runtime_config", lambda: config)
    monkeypatch.setattr(sched_mod, "in_cold_start_window", lambda: True)

    scheduler = ConversationScheduler(concurrency=2, max_pending=32)
    ramp = asyncio.create_task(sched_mod._ramp_up_scheduler(scheduler))
    await asyncio.sleep(0.08)

    assert scheduler.concurrency == 8
    assert scheduler.llm_reserved == 6
    await ramp
    await scheduler.stop()


@pytest.mark.asyncio
async def test_startup_ramp_ends_early_when_window_closed(monkeypatch) -> None:
    config = SimpleNamespace(
        conversation_scheduler_concurrency=8,
        conversation_scheduler_startup_concurrency=2,
        conversation_scheduler_adaptive_interval_sec=0.01,
        conversation_scheduler_llm_reserved=6,
    )
    monkeypatch.setattr(sched_mod, "get_ingress_dispatch_runtime_config", lambda: config)
    calls = {"count": 0}

    def fake_window() -> bool:
        calls["count"] += 1
        return calls["count"] <= 1

    monkeypatch.setattr(sched_mod, "in_cold_start_window", fake_window)

    scheduler = ConversationScheduler(concurrency=2, max_pending=32)
    ramp = asyncio.create_task(sched_mod._ramp_up_scheduler(scheduler))
    await asyncio.wait_for(ramp, timeout=2.0)

    assert scheduler.concurrency == 8
    assert scheduler.llm_reserved == 6
    await scheduler.stop()
