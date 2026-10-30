from __future__ import annotations

import copy
import json

import httpx
import pytest

from pallas.product.llm import provider_client
from pallas.product.llm.config import LlmConfig


FORMATS = [
    {"type": "text"},
    {"type": "json_object"},
    {
        "type": "json_schema",
        "json_schema": {
            "name": "result",
            "description": "Structured fixture",
            "strict": True,
            "schema": {"type": "object", "properties": {"answer": {"type": "string"}}},
        },
    },
]


@pytest.fixture
async def http_probe(monkeypatch):
    requests = []

    def reply(request):
        requests.append(json.loads(request.content))
        if request.url.path.endswith("/responses"):
            return httpx.Response(200, json={
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
            })
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "{}"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as client:
        async def get_client():
            return client

        monkeypatch.setattr(provider_client, "get_llm_shared_httpx_client", get_client)
        monkeypatch.setattr(provider_client, "_record_usage_from_payload", lambda *args, **kwargs: None)
        monkeypatch.setattr(provider_client, "_emit_provider_attempt", lambda **kwargs: None)
        monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)
        yield requests


async def complete(method, options):
    return await provider_client.complete_chat_message(
        [{"role": "user", "content": "Return JSON."}],
        model="proof-model",
        cfg=LlmConfig(llm_chat_enabled=True),
        base_url="https://provider.invalid/v1",
        request_method=method,
        options=options,
    )


@pytest.mark.parametrize("method", ["chat_completions", "responses"])
@pytest.mark.parametrize("response_format", FORMATS)
async def test_response_format_reaches_provider_without_mutation(http_probe, method, response_format):
    options = {"response_format": copy.deepcopy(response_format)}
    original = copy.deepcopy(options)
    await complete(method, options)
    payload = http_probe[0]
    if method == "chat_completions":
        assert payload["response_format"] == response_format
    else:
        expected = response_format
        if response_format["type"] == "json_schema":
            expected = {"type": "json_schema", **response_format["json_schema"]}
        assert payload["text"]["format"] == expected
        assert "response_format" not in payload
    assert options == original


@pytest.mark.parametrize("method", ["chat_completions", "responses"])
async def test_no_response_format_preserves_existing_request(http_probe, method):
    await complete(method, {})
    assert "response_format" not in http_probe[0]
    assert "text" not in http_probe[0]


@pytest.mark.parametrize("method", ["chat_completions", "responses"])
@pytest.mark.parametrize("response_format", [
    "json",
    {"type": "unknown"},
    {"type": "json_schema"},
    {"type": "json_schema", "json_schema": {"name": "", "schema": {}}},
    {"type": "json_schema", "json_schema": {"name": "x", "schema": {}, "strict": "yes"}},
])
async def test_invalid_response_format_is_rejected_before_http(http_probe, method, response_format):
    with pytest.raises(provider_client.LlmProviderError, match="response_format"):
        await complete(method, {"response_format": response_format})
    assert http_probe == []


@pytest.mark.parametrize("method", ["ollama_chat", "anthropic_messages"])
async def test_unsupported_protocol_does_not_silently_drop_format(http_probe, method):
    with pytest.raises(provider_client.LlmProviderError, match="response_format"):
        await complete(method, {"response_format": {"type": "json_object"}})
    assert http_probe == []
