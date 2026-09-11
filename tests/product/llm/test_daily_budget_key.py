from __future__ import annotations

from pallas.product.llm import daily_budget


def test_bump_and_used_separate_by_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    daily_budget.bump_today("provider", key="ds", calls=1, tokens=100, cost=0.5)
    daily_budget.bump_today("provider", key="other", calls=1, tokens=999, cost=9.9)

    assert daily_budget.used_today("provider", key="ds") == {
        "calls": 1.0,
        "tokens": 100.0,
        "cost": 0.5,
    }
    assert daily_budget.used_today("provider", key="other") == {
        "calls": 1.0,
        "tokens": 999.0,
        "cost": 9.9,
    }


def test_key_case_sensitive_matches_provider_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    daily_budget.bump_today("provider", key="DeepSeek", calls=1, tokens=50)
    assert daily_budget.used_today("provider", key="deepseek")["tokens"] == 0.0
    assert daily_budget.used_today("provider", key="DeepSeek")["tokens"] == 50.0


def test_reserve_today_blocks_when_over_limit(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    assert daily_budget.reserve_today("graph", key="graph", count=1, limit=2) is True
    assert daily_budget.reserve_today("graph", key="graph", count=1, limit=2) is True
    assert daily_budget.reserve_today("graph", key="graph", count=1, limit=2) is False
    assert daily_budget.used_today("graph", key="graph")["calls"] == 2.0


def test_reserve_today_batch_is_atomic(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    assert daily_budget.reserve_today("graph", key="graph", count=3, limit=3) is True
    # 超限的批量预占不落任何计数
    assert daily_budget.reserve_today("graph", key="graph", count=2, limit=3) is False
    assert daily_budget.used_today("graph", key="graph")["calls"] == 3.0


def test_reserve_today_zero_limit_means_unlimited(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    assert daily_budget.reserve_today("graph", key="graph", count=5, limit=0) is True
    assert daily_budget.used_today("graph", key="graph")["calls"] == 0.0


def test_reserve_today_separate_by_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    assert daily_budget.reserve_today("graph", key="a", count=1, limit=1) is True
    assert daily_budget.reserve_today("graph", key="b", count=1, limit=1) is True
    assert daily_budget.reserve_today("graph", key="a", count=1, limit=1) is False


def test_natural_day_key_uses_beijing_boundary() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    beijing = ZoneInfo("Asia/Shanghai")

    def ts(year: int, month: int, day: int, hour: int, minute: int) -> int:
        return int(datetime(year, month, day, hour, minute, tzinfo=beijing).timestamp())

    # 北京同一自然日的凌晨、早晨、跨过旧 UTC 边界（08:00）都同键
    assert daily_budget.natural_day_key(ts(2026, 9, 11, 0, 30)) == "2026-09-11"
    assert daily_budget.natural_day_key(ts(2026, 9, 11, 7, 30)) == "2026-09-11"
    assert daily_budget.natural_day_key(ts(2026, 9, 11, 8, 30)) == "2026-09-11"
    assert daily_budget.natural_day_key(ts(2026, 9, 11, 23, 59)) == "2026-09-11"
    # 过北京零点才翻页
    assert daily_budget.natural_day_key(ts(2026, 9, 12, 0, 1)) == "2026-09-12"
    # 日零点对齐北京零点，而非 UTC 零点
    assert daily_budget.natural_day_start(ts(2026, 9, 11, 13, 0)) == ts(2026, 9, 11, 0, 0)


def test_budget_buckets_follow_natural_day(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    monkeypatch.setattr(daily_budget, "natural_day_key", lambda now=None: "2026-09-11")
    daily_budget.bump_today("provider", key="x", calls=1, tokens=10)
    assert daily_budget.used_today("provider", key="x")["calls"] == 1.0
    assert daily_budget.reserve_today("graph", key="x", count=1, limit=1) is True
    assert daily_budget.reserve_today("graph", key="x", count=1, limit=1) is False

    monkeypatch.setattr(daily_budget, "natural_day_key", lambda now=None: "2026-09-12")
    assert daily_budget.used_today("provider", key="x")["calls"] == 0.0
    assert daily_budget.reserve_today("graph", key="x", count=1, limit=1) is True
