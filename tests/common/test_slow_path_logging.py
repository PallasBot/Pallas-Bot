from __future__ import annotations

from typing import Any

from pallas.core.platform.observability import slow_path


def test_slow_path_logs_stages_when_threshold_exceeded(monkeypatch) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        slow_path,
        "log_rate_limited",
        lambda logger, level, key, msg, *args, **kwargs: calls.append((level, key, msg, args)),
    )

    timer = slow_path.SlowPathTimer("ingress_gate", threshold_ms=10.0)
    timer._started = 1.0
    timer._last_mark = 1.0
    timer.mark("dedup", now=1.008)
    timer.mark("federate", now=1.017)
    timer.finish(outcome="pass", now=1.024, group_id=12345)

    assert len(calls) == 1
    level, key, msg, args = calls[0]
    assert level == "debug"
    assert key == "slow_path.ingress_gate"
    assert "慢路径耗时" in msg
    assert args[0] == "ingress_gate"
    assert "dedup [8.0ms]" in args[2]
    assert "federate [9.0ms]" in args[2]
    assert "group_id [12345]" in args[3]
    assert "outcome [pass]" in args[3]


def test_slow_path_skips_log_below_threshold(monkeypatch) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        slow_path,
        "log_rate_limited",
        lambda logger, level, key, msg, *args, **kwargs: calls.append((level, key, msg, args)),
    )

    timer = slow_path.SlowPathTimer("federate_ingress", threshold_ms=50.0)
    timer._started = 1.0
    timer.mark("redis", now=1.015)
    timer.finish(outcome="pass", now=1.030, cache_hit=True)

    assert calls == []


def test_slow_path_can_log_at_debug_level(monkeypatch) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        slow_path,
        "log_rate_limited",
        lambda logger, level, key, msg, *args, **kwargs: calls.append((level, key, msg, args)),
    )

    timer = slow_path.SlowPathTimer("federate_ingress", threshold_ms=10.0, log_level="debug")
    timer._started = 1.0
    timer.mark("redis", now=1.012)
    timer.finish(outcome="won", now=1.020, cache_hit=False)

    assert len(calls) == 1
    assert calls[0][0] == "debug"
    assert calls[0][1] == "slow_path.federate_ingress"
