"""LLM token 费用计算。"""

from __future__ import annotations

from pallas.product.llm.providers_store import (
    clear_providers_store_cache,
    save_providers_document,
)
from pallas.product.llm.token_cost import (
    compute_usage_cost,
    cost_for_usage,
    normalize_cost_currency,
    normalize_model_pricing,
)
from pallas.product.llm.token_metrics import (
    clear_llm_token_metrics_for_tests,
    llm_token_metrics_snapshot,
    record_llm_token_usage,
)


def test_normalize_cost_currency() -> None:
    assert normalize_cost_currency("cny") == "CNY"
    assert normalize_cost_currency("  usd ") == "USD"
    assert normalize_cost_currency("") == ""


def test_compute_usage_cost_with_cache() -> None:
    # 1M input @ 1 + 0.5M cache @ 0.1 + 0.1M out @ 2
    cost = compute_usage_cost(
        prompt_tokens=1_000_000,
        completion_tokens=100_000,
        cache_read_tokens=500_000,
        cache_write_tokens=0,
        price_in=1.0,
        price_out=2.0,
        cache_price_in=0.1,
    )
    assert abs(cost - (1.0 + 0.2 + 0.05)) < 1e-9


def test_normalize_model_pricing_drops_empty() -> None:
    assert normalize_model_pricing({"m": {"price_in": 0, "price_out": 0}}) == {}
    assert normalize_model_pricing({"m": {"price_in": 1.5, "price_out": 2}}) == {
        "m": {"price_in": 1.5, "price_out": 2.0, "cache_price_in": 0.0, "cache_price_out": 0.0}
    }


def test_record_usage_accumulates_configured_cost(tmp_path, monkeypatch) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    clear_providers_store_cache()
    save_providers_document(
        {
            "providers": [
                {
                    "id": "ds",
                    "kind": "remote",
                    "base_url": "https://api.example.com",
                    "api_key": "sk-x",
                    "default_model": "deepseek-chat",
                    "model_pricing": {
                        "deepseek-chat": {
                            "price_in": 1.0,
                            "price_out": 2.0,
                            "cache_price_in": 0.1,
                        }
                    },
                }
            ],
            "routing": {"tasks": {"llm_chat": "ds"}, "cost_currency": "cny"},
        }
    )
    clear_llm_token_metrics_for_tests()
    record_llm_token_usage(
        task="llm_chat",
        provider="ds",
        model="deepseek-chat",
        prompt_tokens=1_000_000,
        completion_tokens=500_000,
        cache_read_tokens=100_000,
    )
    snap = llm_token_metrics_snapshot(include_persisted=False)
    assert snap["cost_currency"] == "CNY"
    # 1*1 + 0.5*2 + 0.1*0.1 = 2.01
    assert abs(float(snap["cost_total"]) - 2.01) < 1e-9
    assert abs(float(snap["by_model"]["deepseek-chat"]["cost_total"]) - 2.01) < 1e-9
    cost, currency = cost_for_usage(
        provider_id="ds",
        model="deepseek-chat",
        prompt_tokens=0,
        completion_tokens=0,
    )
    assert cost == 0.0
    assert currency == "CNY"
