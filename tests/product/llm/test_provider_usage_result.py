"""Provider token usage exposed on the corresponding completion result."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest


def test_remote_usage_preserves_prompt_without_cache_split() -> None:
    from pallas.product.llm.token_usage import usage_from_remote_chat_response

    assert usage_from_remote_chat_response(
        {"usage": {"prompt_tokens": 10, "prompt_cache_miss_tokens": 7}}
    ) == (10, 0, 0, 0)


@pytest.fixture
def usage_records(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from pallas.product.llm import daily_budget, token_metrics

    monkeypatch.setattr(daily_budget, "_budget_path", lambda name: tmp_path / f"{name}_budget.json")
    calls = []
    record = token_metrics.record_llm_token_usage

    def spy(**kwargs):
        calls.append(kwargs)
        record(**kwargs)

    monkeypatch.setattr(token_metrics, "record_llm_token_usage", spy)
    return calls


async def _complete_with_client(
    monkeypatch: pytest.MonkeyPatch,
    client: httpx.AsyncClient,
    *,
    model: str = "demo",
    request_method: str = "chat_completions",
    base_url: str | None = "https://example.test/v1",
    provider_id: str = "",
):
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm import provider_client as pc

    async def get_client() -> httpx.AsyncClient:
        return client

    monkeypatch.setattr(pc, "get_llm_shared_httpx_client", get_client)
    kwargs = {
        "model": model,
        "cfg": LlmConfig(chat_timeout_sec=5.0, llm_chat_enabled=True),
        "request_method": request_method,
        "provider_id": provider_id,
    }
    if base_url is not None:
        kwargs["base_url"] = base_url
    return await pc.complete_chat_message([{"role": "user", "content": "hi"}], **kwargs)


@pytest.mark.asyncio
async def test_missing_and_zero_usage_are_distinguished_on_http_results(
    monkeypatch: pytest.MonkeyPatch,
    usage_records,
) -> None:
    from pallas.product.llm import provider_client as pc

    payloads = [
        {"choices": [{"message": {"role": "assistant", "content": "no usage"}}]},
        {
            "choices": [{"message": {"role": "assistant", "content": "empty usage"}}],
            "usage": {},
        },
        {
            "choices": [{"message": {"role": "assistant", "content": "metadata only"}}],
            "usage": {"unrelated_metadata": "provider detail"},
        },
        {
            "choices": [{"message": {"role": "assistant", "content": "malformed usage"}}],
            "usage": {"prompt_tokens": "not-a-token-count"},
        },
        {
            "choices": [{"message": {"role": "assistant", "content": "zero usage"}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        },
    ]

    async def reply(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads.pop(0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        missing = await _complete_with_client(monkeypatch, client)
        empty = await _complete_with_client(monkeypatch, client)
        metadata = await _complete_with_client(monkeypatch, client)
        malformed = await _complete_with_client(monkeypatch, client)
        zero = await _complete_with_client(monkeypatch, client)

    assert "_provider_usage" not in missing
    assert "_provider_usage" not in empty
    assert "_provider_usage" not in metadata
    assert "_provider_usage" not in malformed
    assert zero["_provider_usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
    }
    assert len(usage_records) == 4


@pytest.mark.parametrize(
    ("request_method", "payload", "expected"),
    [
        # Nonstandard cache_creation_tokens; possible overlap with prompt is unknown and not inferred.
        (
            "chat_completions",
            {
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 3,
                    "prompt_tokens_details": {"cached_tokens": 4, "cache_creation_tokens": 1},
                },
            },
            {"prompt_tokens": 6, "completion_tokens": 3, "cache_read_tokens": 4, "cache_write_tokens": 1},
        ),
        (
            "chat_completions",
            {
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 3,
                    "total_tokens": 13,
                    "prompt_tokens_details": {"cached_tokens": 4},
                },
            },
            {"prompt_tokens": 6, "completion_tokens": 3, "cache_read_tokens": 4, "cache_write_tokens": 0},
        ),
        # Nonstandard cache_write_tokens; possible overlap with prompt is unknown and not inferred.
        (
            "responses",
            {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 2,
                    "input_tokens_details": {"cached_tokens": 4, "cache_write_tokens": 1},
                },
            },
            {"prompt_tokens": 7, "completion_tokens": 2, "cache_read_tokens": 4, "cache_write_tokens": 1},
        ),
        (
            "responses",
            {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 2,
                    "total_tokens": 13,
                    "input_tokens_details": {"cached_tokens": 4},
                },
            },
            {"prompt_tokens": 7, "completion_tokens": 2, "cache_read_tokens": 4, "cache_write_tokens": 0},
        ),
        (
            "anthropic_messages",
            {
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 4,
                    "cache_creation_input_tokens": 2,
                },
            },
            {"prompt_tokens": 12, "completion_tokens": 5, "cache_read_tokens": 4, "cache_write_tokens": 2},
        ),
        (
            "ollama_chat",
            {
                "message": {"role": "assistant", "content": "ok"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 8,
                "eval_count": 2,
            },
            {"prompt_tokens": 8, "completion_tokens": 2, "cache_read_tokens": 0, "cache_write_tokens": 0},
        ),
    ],
)
@pytest.mark.asyncio
async def test_protocol_usage_is_normalized_and_recorded_once(
    monkeypatch: pytest.MonkeyPatch,
    usage_records,
    request_method: str,
    payload: dict,
    expected: dict[str, int],
) -> None:
    async def reply(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await _complete_with_client(monkeypatch, client, request_method=request_method)

    assert result["content"] == "ok"
    assert result["_provider_usage"] == {
        **expected,
        "total_tokens": sum(expected.values()),
    }
    if "total_tokens" in payload.get("usage", {}):
        assert result["_provider_usage"]["total_tokens"] == payload["usage"]["total_tokens"]
    assert len(usage_records) == 1
    assert usage_records[0]["prompt_tokens"] == expected["prompt_tokens"]
    assert usage_records[0]["completion_tokens"] == expected["completion_tokens"]
    assert usage_records[0]["cache_read_tokens"] == expected["cache_read_tokens"]
    assert usage_records[0]["cache_write_tokens"] == expected["cache_write_tokens"]
    assert usage_records[0]["prompt_tokens"] == result["_provider_usage"]["prompt_tokens"]
    if request_method == "anthropic_messages":
        from pallas.product.llm import usage_ledger

        rows = [
            json.loads(line)
            for path in usage_ledger.usage_ledger_dir().glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert rows[-1]["prompt_tokens"] == result["_provider_usage"]["prompt_tokens"] == 12


@pytest.mark.asyncio
async def test_concurrent_requests_keep_usage_with_their_own_result(
    monkeypatch: pytest.MonkeyPatch,
    usage_records,
) -> None:
    payloads = {
        "first": {
            "choices": [{"message": {"role": "assistant", "content": "first"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 1},
        },
        "second": {
            "choices": [{"message": {"role": "assistant", "content": "second"}}],
            "usage": {"prompt_tokens": 22, "completion_tokens": 2},
        },
    }

    async def reply(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model == "first":
            await asyncio.sleep(0.01)
        return httpx.Response(200, json=payloads[model])

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        first, second = await asyncio.gather(
            _complete_with_client(monkeypatch, client, model="first"),
            _complete_with_client(monkeypatch, client, model="second"),
        )

    assert first["_provider_usage"]["total_tokens"] == 12
    assert second["_provider_usage"]["total_tokens"] == 24
    assert len(usage_records) == 2


@pytest.mark.asyncio
async def test_key_failover_returns_only_selected_response_usage(
    monkeypatch: pytest.MonkeyPatch,
    usage_records,
) -> None:
    from pallas.product.llm import provider_client as pc
    from pallas.product.llm.providers_store import ResolvedLlmEndpoint

    calls: list[str] = []

    async def reply(request: httpx.Request) -> httpx.Response:
        key = request.headers.get("authorization", "")
        calls.append(key)
        if key == "Bearer bad":
            return httpx.Response(429, text="busy")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "selected"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    monkeypatch.setattr(pc, "provider_daily_budget_ok", lambda _provider: True)
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_candidates_for_task",
        lambda _task: [
            ResolvedLlmEndpoint(
                provider_id="provider",
                base_url="https://example.test/v1",
                api_key="bad",
                model="demo",
                api_keys=("bad", "good"),
            )
        ],
    )
    monkeypatch.setattr("pallas.product.llm.providers_store.find_provider", lambda _provider: None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await _complete_with_client(
            monkeypatch,
            client,
            base_url=None,
            request_method="chat_completions",
        )

    assert calls == ["Bearer bad", "Bearer good"]
    assert result["content"] == "selected"
    assert result["_provider_usage"]["total_tokens"] == 10
    assert len(usage_records) == 1
    assert usage_records[0]["prompt_tokens"] == 7


@pytest.mark.asyncio
async def test_provider_budget_rejection_sends_no_http_or_usage_record(
    monkeypatch: pytest.MonkeyPatch,
    usage_records,
) -> None:
    from pallas.product.llm import provider_client as pc

    requests: list[httpx.Request] = []

    async def reply(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "unexpected"}}]})

    monkeypatch.setattr(pc, "provider_daily_budget_ok", lambda _provider: False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(pc.LlmProviderError, match="daily budget exhausted"):
            await _complete_with_client(monkeypatch, client, provider_id="capped-provider")

    assert requests == []
    assert usage_records == []


@pytest.mark.asyncio
async def test_usage_survives_token_recording_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import provider_client as pc, token_metrics

    async def reply(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    def fail_recording(**_kwargs) -> None:
        raise OSError("ledger unavailable")

    monkeypatch.setattr(token_metrics, "record_llm_token_usage", fail_recording)
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await _complete_with_client(monkeypatch, client)

    assert result["_provider_usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 2,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 7,
    }


@pytest.mark.asyncio
async def test_usage_survives_token_metrics_import_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fail_metrics_import(name, *args, **kwargs):
        if name == "pallas.product.llm.token_metrics":
            raise ImportError("token metrics unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_metrics_import)

    async def reply(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await _complete_with_client(monkeypatch, client)

    assert result["_provider_usage"]["prompt_tokens"] == 5
