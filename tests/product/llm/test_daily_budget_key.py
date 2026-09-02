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
