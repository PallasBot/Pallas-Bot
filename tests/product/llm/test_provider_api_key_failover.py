"""Provider 多密钥 failover。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm.provider_client import (
    LlmProviderError,
    endpoint_api_keys,
    mask_api_key_hint,
    should_failover_api_key,
)
from pallas.product.llm.providers_store import resolve_provider_api_keys


def test_resolve_provider_api_keys_preserves_order() -> None:
    assert resolve_provider_api_keys({"api_keys": ["sk-b", "sk-a"], "api_key": "sk-b"}) == [
        "sk-b",
        "sk-a",
    ]
    assert resolve_provider_api_keys({"api_key": "sk-only"}) == ["sk-only"]
    assert resolve_provider_api_keys({}) == []


def test_should_failover_api_key_statuses() -> None:
    assert should_failover_api_key(LlmProviderError("x", status=401)) is True
    assert should_failover_api_key(LlmProviderError("x", status=403)) is True
    assert should_failover_api_key(LlmProviderError("x", status=429)) is True
    assert should_failover_api_key(LlmProviderError("x", status=502)) is True
    assert should_failover_api_key(LlmProviderError("x", status=503)) is True
    assert should_failover_api_key(LlmProviderError("x", status=400)) is False
    assert should_failover_api_key(LlmProviderError("x", status=500)) is False
    assert should_failover_api_key(RuntimeError("x")) is False


def test_mask_api_key_hint() -> None:
    assert mask_api_key_hint("sk-abcdefgh") == "sk-abc*****fgh"
    assert mask_api_key_hint("short-key") == "****"


def test_endpoint_api_keys_prefers_tuple() -> None:
    endpoint = SimpleNamespace(api_key="sk-old", api_keys=("sk-1", "sk-2"))
    assert endpoint_api_keys(endpoint, fallback="sk-fb") == ["sk-1", "sk-2"]
    endpoint2 = SimpleNamespace(api_key="sk-single", api_keys=())
    assert endpoint_api_keys(endpoint2, fallback="sk-fb") == ["sk-single"]


@pytest.mark.asyncio
async def test_chat_tries_next_api_key_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import provider_client as pc
    from pallas.product.llm.providers_store import ResolvedLlmEndpoint

    calls: list[str] = []

    async def fake_post(*_args, **kwargs):
        key = str(kwargs.get("api_key") or "")
        calls.append(key)
        if key == "sk-bad":
            raise LlmProviderError("rate", status=429)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(pc, "_post_provider_chat", fake_post)
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_candidates_for_task",
        lambda _task: [
            ResolvedLlmEndpoint(
                provider_id="p1",
                base_url="https://example.com/v1",
                api_key="sk-bad",
                model="m1",
                api_keys=("sk-bad", "sk-good"),
            )
        ],
    )
    monkeypatch.setattr(
        pc,
        "get_llm_config",
        lambda: SimpleNamespace(llm_api_key="", llm_model="", chat_timeout_sec=10.0),
    )

    result = await pc.complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="m1",
        task="llm_chat",
    )
    assert calls == ["sk-bad", "sk-good"]
    assert result["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
async def test_chat_does_not_failover_key_on_400(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import provider_client as pc
    from pallas.product.llm.providers_store import ResolvedLlmEndpoint

    calls: list[str] = []

    async def fake_post(*_args, **kwargs):
        key = str(kwargs.get("api_key") or "")
        calls.append(key)
        raise LlmProviderError("bad request", status=400)

    monkeypatch.setattr(pc, "_post_provider_chat", fake_post)
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_candidates_for_task",
        lambda _task: [
            ResolvedLlmEndpoint(
                provider_id="p1",
                base_url="https://example.com/v1",
                api_key="sk-1",
                model="m1",
                api_keys=("sk-1", "sk-2"),
            )
        ],
    )
    monkeypatch.setattr(
        pc,
        "get_llm_config",
        lambda: SimpleNamespace(llm_api_key="", llm_model="", chat_timeout_sec=10.0),
    )

    with pytest.raises(LlmProviderError) as exc_info:
        await pc.complete_chat_message(
            [{"role": "user", "content": "hi"}],
            model="m1",
            task="llm_chat",
        )
    assert exc_info.value.status == 400
    assert calls == ["sk-1"]
