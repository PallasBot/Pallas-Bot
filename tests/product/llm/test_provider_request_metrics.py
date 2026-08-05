"""Bot 侧 LLM 提供方请求计量。"""

from __future__ import annotations

import pytest

from pallas.product.llm.provider_request_metrics import (
    clear_llm_provider_request_metrics_for_tests,
    llm_provider_request_metrics_snapshot,
    record_provider_request,
)


@pytest.mark.asyncio
async def test_complete_chat_message_returns_sanitized_provider_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.provider_client import complete_chat_message

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return {"choices": [{"message": {"role": "assistant", "content": "你好"}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr("pallas.product.llm.provider_client.httpx.AsyncClient", FakeClient)
    result = await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="demo",
        base_url="https://example.test/v1",
        api_key="sk-test",
        provider_id="demo-provider",
        cfg=LlmConfig(chat_timeout_sec=5.0),
    )

    trace = result["_provider_trace"]
    assert trace["provider"] == "demo-provider"
    assert trace["model"] == "demo"
    assert trace["request_method"] == "chat_completions"
    assert trace["ok"] is True
    assert isinstance(trace["latency_ms"], int)


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
