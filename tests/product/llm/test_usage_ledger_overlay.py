"""账本覆盖日历史与脏数据清洗。"""

from __future__ import annotations

from pallas.product.llm.model_admin import _overlay_ledger_on_history_rows
from pallas.product.llm.usage_ledger import append_usage_record


def test_overlay_prefers_ledger_and_sanitizes_corrupt(tmp_path, monkeypatch) -> None:
    root = tmp_path / "llm_usage"
    monkeypatch.setattr(
        "pallas.product.llm.usage_ledger.usage_ledger_dir",
        lambda: root,
    )
    append_usage_record(
        task="llm_chat",
        provider="ds",
        model="m",
        prompt_tokens=50,
        completion_tokens=5,
        cost=0.01,
        currency="CNY",
        day_key="2026-07-25",
    )
    rows = [
        {
            "date": "2026-07-20",
            "ai": {
                "source": "ai",
                "tokens": {
                    "prompt_tokens": 17_000_000_000,
                    "completion_tokens": 1,
                    "total_tokens": 17_000_000_001,
                    "cost_total": 0,
                },
                "gates": {"proceed": 1, "skip": 0, "defer": 0},
            },
        },
        {
            "date": "2026-07-25",
            "ai": {
                "source": "bot",
                "tokens": {
                    "prompt_tokens": 999,
                    "completion_tokens": 1,
                    "total_tokens": 1000,
                    "cost_total": 0,
                },
            },
        },
    ]
    out = _overlay_ledger_on_history_rows(rows, start_day="2026-07-20", end_day="2026-07-26")
    by_date = {r["date"]: r for r in out}
    assert by_date["2026-07-20"]["ai"]["tokens"]["total_tokens"] == 0
    assert by_date["2026-07-20"]["ai"]["gates"]["proceed"] == 1
    assert by_date["2026-07-25"]["ai"]["tokens"]["prompt_tokens"] == 50
    assert abs(float(by_date["2026-07-25"]["ai"]["tokens"]["cost_total"]) - 0.01) < 1e-9
