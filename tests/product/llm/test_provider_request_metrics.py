"""Bot 侧 LLM 提供方请求计量。"""

from __future__ import annotations

from pallas.product.llm.provider_request_metrics import (
    clear_llm_provider_request_metrics_for_tests,
    llm_provider_request_metrics_snapshot,
    record_provider_request,
)


def test_record_provider_request_success_and_failure() -> None:
    clear_llm_provider_request_metrics_for_tests()
    record_provider_request(provider="openai", model="gpt-4.1-mini", ok=True, latency_ms=120)
    record_provider_request(
        provider="openai",
        model="gpt-4.1-mini",
        ok=False,
        latency_ms=80,
        failure_class="http_429",
    )
    record_provider_request(provider="deepseek", model="deepseek-chat", ok=True, latency_ms=200)

    snap = llm_provider_request_metrics_snapshot(include_persisted=False)
    assert snap["provider_stats"]["openai"]["requests"] == 2
    assert snap["provider_stats"]["openai"]["succeeded"] == 1
    assert snap["provider_stats"]["openai"]["failed"] == 1
    assert snap["provider_stats"]["openai"]["avg_latency_ms"] == 100
    assert snap["provider_stats"]["openai"]["recent_failure_class"] == "http_429"
    assert snap["provider_stats"]["deepseek"]["succeeded"] == 1
    assert snap["model_stats"]["gpt-4.1-mini"]["requests"] == 2
    assert snap["failure_counts"]["http_429"] == 1
