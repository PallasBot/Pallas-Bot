"""请求级 LLM usage 账本。"""

from __future__ import annotations

from pallas.product.llm.usage_ledger import (
    aggregate_day_from_ledger,
    append_usage_record,
    tokens_look_corrupt,
)


def test_append_and_aggregate_day(tmp_path, monkeypatch) -> None:
    root = tmp_path / "llm_usage"
    monkeypatch.setattr(
        "pallas.product.llm.usage_ledger.usage_ledger_dir",
        lambda: root,
    )
    monkeypatch.setattr(
        "pallas.product.llm.token_metrics.today_key",
        lambda: "2026-07-26",
    )
    # 2026-07-26 13:00:00 / 14:00:00 local
    ts_afternoon = 1785042000.0
    append_usage_record(
        task="llm_chat",
        provider="ds",
        model="deepseek-v4-flash",
        prompt_tokens=1000,
        completion_tokens=100,
        cache_read_tokens=500,
        cost=0.0013,
        currency="cny",
        day_key="2026-07-26",
        ts=ts_afternoon,
    )
    append_usage_record(
        task="repeater_select",
        provider="local",
        model="qwen2.5:0.5b",
        prompt_tokens=200,
        completion_tokens=10,
        cost=0.0,
        currency="CNY",
        day_key="2026-07-26",
        ts=ts_afternoon + 3600,
    )
    bucket = aggregate_day_from_ledger("2026-07-26")
    assert bucket is not None
    assert bucket["prompt_tokens"] == 1200
    assert bucket["completion_tokens"] == 110
    assert bucket["cache_read_tokens"] == 500
    assert bucket["request_count"] == 2
    assert abs(float(bucket["cost_total"]) - 0.0013) < 1e-9
    assert bucket["cost_currency"] == "CNY"
    assert bucket["by_model"]["deepseek-v4-flash"]["prompt_tokens"] == 1000
    assert bucket["by_hour"]["13"]["total_tokens"] == 1100
    assert bucket["by_hour"]["14"]["total_tokens"] == 210
    assert (root / "2026-07-26.jsonl").is_file()


def test_tokens_look_corrupt() -> None:
    assert tokens_look_corrupt({"total_tokens": 17_000_000_000})
    assert tokens_look_corrupt({"prompt_tokens": 60_000_000, "completion_tokens": 0})
    assert not tokens_look_corrupt({"total_tokens": 186_000})
