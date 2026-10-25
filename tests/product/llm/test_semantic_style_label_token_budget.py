"""语义风格标注输出预算：单条 / 批量 options 及 chat_completions 最终序列化。"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from pallas.product.llm.inference_params import task_token_budget


@pytest.mark.parametrize(
    ("model", "method", "native_disable"),
    [
        ("qwen3.7-flash", "chat_completions", True),
        ("qwen3.7-plus", "chat_completions", True),
        ("deepseek-v4.1-flash", "chat_completions", False),
        ("qwen3.7-flash", "responses", False),
    ],
)
def test_qwen_chat_disable_uses_native_enable_thinking(model, method, native_disable) -> None:
    from pallas.product.llm.provider_client.mapping import apply_model_effort_to_payload

    payload = {"model": model, "max_tokens": 4096}
    apply_model_effort_to_payload(payload, {"model_effort": "disable"}, model=model, request_method=method)

    if native_disable:
        assert payload["enable_thinking"] is False
    else:
        assert "enable_thinking" not in payload


class _OkResponse:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = b""
    text = ""

    def json(self) -> dict:
        return {"choices": [{"message": {"role": "assistant", "content": "{}"}}]}


def _sse_response(*chunks: dict) -> SimpleNamespace:
    frames = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    return SimpleNamespace(
        status_code=200,
        headers={"content-type": "text/event-stream"},
        content=b"",
        text=f"{frames}data: [DONE]\n\n",
    )


def _capture_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider_id: str,
    response,
    models: list[dict] | None = None,
):
    """安装共享 httpx 客户端桩，返回 (complete_chat_message, 捕获的 payload 列表)。"""
    from pallas.product.llm.provider_client import complete_chat_message

    payloads: list[dict] = []
    provider_row: dict = {"id": str(provider_id or ""), "model_effort": "disable"}
    if models is not None:
        provider_row["models"] = models

    class FakeClient:
        async def post(self, _url, *, json=None, **_kwargs):
            payloads.append(json)
            return response

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr("pallas.product.llm.provider_client.get_llm_shared_httpx_client", fake_client)
    monkeypatch.setattr("pallas.product.llm.availability.llm_calls_enabled", lambda cfg=None: True)
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.find_provider",
        lambda pid, **_kwargs: provider_row,
    )
    return complete_chat_message, payloads


def _stub_semantic_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: SimpleNamespace(llm_model="test-model"),
    )
    monkeypatch.setattr(
        "pallas.product.llm.repeater_semantic_style.claim_semantic_label_budget",
        lambda n=1: True,
    )


@pytest.mark.asyncio
async def test_single_label_uses_widened_text_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    captured: list[dict] = []

    async def fake_complete(messages, *, model=None, options=None, cfg=None, task=None):
        captured.append(options)
        return {"content": "{}"}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", fake_complete)
    _stub_semantic_config(monkeypatch)

    await mod.label_semantic_style_with_llm(trigger_text="前句", reply_text="接话")

    assert captured == [{"temperature": 0, "max_tokens": 2048}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pair_count", "expected"),
    [
        (1, [2048]),
        (4, [2048]),
        (5, [2560]),
        (8, [4096]),
        (9, [4096, 2048]),
    ],
)
async def test_batch_label_budget_scales_per_chunk(
    monkeypatch: pytest.MonkeyPatch, pair_count: int, expected: list[int]
) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    seen: list[int] = []

    async def fake_complete(messages, *, model=None, options=None, cfg=None, task=None):
        seen.append(options["max_tokens"])
        count = int(re.search(r"判断 (\d+) 组", str(messages[0]["content"])).group(1))
        return {"content": json.dumps([{"is_reply_pair": True, "transferable": True}] * count)}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", fake_complete)
    _stub_semantic_config(monkeypatch)

    pairs = [(f"前句{i}", f"接话{i}", "adjacent") for i in range(pair_count)]
    results = await mod.label_semantic_style_batch_with_llm(pairs)

    assert seen == expected
    assert len(results) == pair_count


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["deepseek-v4.1-flash", "qwen3.7-flash"])
async def test_semantic_style_budget_serializes_to_chat_completions(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    complete_chat_message, payloads = _capture_chat_completions(
        monkeypatch, provider_id="deepseek-test", response=_OkResponse()
    )

    await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model=model,
        options={"temperature": 0, "max_tokens": task_token_budget("repeater.semantic_style")},
        cfg=SimpleNamespace(llm_api_key="sk", llm_model=model, chat_timeout_sec=10.0),
        base_url="https://provider.example/v1",
        api_key="sk",
        task="repeater.semantic_style",
        provider_id="deepseek-test",
    )

    assert payloads[0]["max_tokens"] == 2048
    assert payloads[0]["thinking"] == {"type": "disabled"}
    if model.startswith("qwen"):
        assert payloads[0]["enable_thinking"] is False
    else:
        assert "enable_thinking" not in payloads[0]
    assert "tools" not in payloads[0]
    # 非 CPA provider 走非流式，只有 CPA 分支才打开 stream
    assert "stream" not in payloads[0]


@pytest.mark.asyncio
async def test_cpa_serializes_semantic_style_budget_over_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _sse_response(
        {"choices": [{"index": 0, "delta": {"content": "{}"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    )
    complete_chat_message, payloads = _capture_chat_completions(monkeypatch, provider_id="cpa", response=response)

    message = await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="deepseek-v4.1-flash",
        options={"temperature": 0, "max_tokens": task_token_budget("repeater.semantic_style")},
        cfg=SimpleNamespace(llm_api_key="sk", llm_model="deepseek-v4.1-flash", chat_timeout_sec=10.0),
        base_url="https://provider.example/v1",
        api_key="sk",
        task="repeater.semantic_style",
        provider_id="cpa",
    )

    assert payloads[0]["stream"] is True
    assert payloads[0]["max_tokens"] == 2048
    assert payloads[0]["thinking"] == {"type": "disabled"}
    assert "tools" not in payloads[0]
    assert message["content"] == "{}"


@pytest.mark.asyncio
async def test_cpa_reasoning_only_length_finish_raises_incomplete_token_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CPA SSE 只有 reasoning 且 finish_reason=length：本地按截断失败处理，不误判为成功。"""
    from pallas.product.llm.provider_client import LlmProviderError

    response = _sse_response(
        {"choices": [{"index": 0, "delta": {"reasoning_content": "只思考未作答"}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
    )
    complete_chat_message, payloads = _capture_chat_completions(monkeypatch, provider_id="cpa", response=response)

    with pytest.raises(LlmProviderError) as excinfo:
        await complete_chat_message(
            [{"role": "user", "content": "hi"}],
            model="deepseek-v4.1-flash",
            options={"temperature": 0, "max_tokens": task_token_budget("repeater.semantic_style")},
            cfg=SimpleNamespace(llm_api_key="sk", llm_model="deepseek-v4.1-flash", chat_timeout_sec=10.0),
            base_url="https://provider.example/v1",
            api_key="sk",
            task="repeater.semantic_style",
            provider_id="cpa",
        )

    assert excinfo.value.failure_class == "incomplete_token_limit"
    assert payloads[0]["stream"] is True


def _semantic_vocab_words() -> set[str]:
    from pallas.product.llm import repeater_semantic_style as mod

    return set(mod.INTERACTION_ACTION_VOCABULARY) | set(mod.SEMANTIC_RELATION_VOCABULARY) | set(mod.FORM_VOCABULARY)


def _missing_vocab_words(prompt: str) -> set[str]:
    return {word for word in _semantic_vocab_words() if word not in prompt}


@pytest.mark.asyncio
async def test_single_prompt_enumerates_parser_vocabularies(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    prompts: list[str] = []

    async def fake_complete(messages, *, model=None, options=None, cfg=None, task=None):
        prompts.append(str(messages[0]["content"]))
        return {"content": "{}"}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", fake_complete)
    _stub_semantic_config(monkeypatch)

    await mod.label_semantic_style_with_llm(trigger_text="前句", reply_text="接话")

    assert "interaction_actions" in prompts[0]
    assert "semantic_relations" in prompts[0]
    assert "forms" in prompts[0]
    assert _missing_vocab_words(prompts[0]) == set()


@pytest.mark.asyncio
async def test_batch_prompt_enumerates_parser_vocabularies(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import repeater_semantic_style as mod

    prompts: list[str] = []

    async def fake_complete(messages, *, model=None, options=None, cfg=None, task=None):
        prompts.append(str(messages[0]["content"]))
        return {"content": json.dumps([{"is_reply_pair": True, "transferable": True}])}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", fake_complete)
    _stub_semantic_config(monkeypatch)

    await mod.label_semantic_style_batch_with_llm([("前句", "接话", "adjacent")])

    assert "interaction_actions" in prompts[0]
    assert "semantic_relations" in prompts[0]
    assert "forms" in prompts[0]
    assert _missing_vocab_words(prompts[0]) == set()


def _enumerated_label_item() -> dict:
    from pallas.product.llm import repeater_semantic_style as mod

    return {
        "is_reply_pair": True,
        "transferable": True,
        "interaction_actions": sorted(mod.INTERACTION_ACTION_VOCABULARY)[:3],
        "semantic_relations": sorted(mod.SEMANTIC_RELATION_VOCABULARY)[:3],
        "intensity": "sharp",
        "forms": sorted(mod.FORM_VOCABULARY)[:3],
    }


async def _run_label_path(monkeypatch: pytest.MonkeyPatch, *, batch: bool, item: dict):
    from pallas.product.llm import repeater_semantic_style as mod

    async def fake_complete(messages, *, model=None, options=None, cfg=None, task=None):
        content = json.dumps([item]) if batch else json.dumps(item)
        return {"content": content}

    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", fake_complete)
    _stub_semantic_config(monkeypatch)

    if batch:
        results = await mod.label_semantic_style_batch_with_llm([("前句", "接话", "adjacent")])
        return results[0][0]
    parsed = await mod.label_semantic_style_with_llm(trigger_text="前句", reply_text="接话")
    return parsed[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_enumerated_vocab_output_survives_parser(monkeypatch: pytest.MonkeyPatch, batch: bool) -> None:
    item = _enumerated_label_item()
    label = await _run_label_path(monkeypatch, batch=batch, item=item)

    assert label.interaction_actions == item["interaction_actions"]
    assert label.semantic_relations == item["semantic_relations"]
    assert label.forms == item["forms"]
    assert label.intensity == "sharp"


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_out_of_vocab_words_still_filtered(monkeypatch: pytest.MonkeyPatch, batch: bool) -> None:
    item = {
        "is_reply_pair": True,
        "transferable": True,
        "interaction_actions": ["tease", "advise"],
        "semantic_relations": ["echo", "reassure"],
        "forms": ["short", "essay"],
    }
    label = await _run_label_path(monkeypatch, batch=batch, item=item)

    assert label.interaction_actions == ["tease"]
    assert label.semantic_relations == ["echo"]
    assert label.forms == ["short"]


@pytest.mark.asyncio
async def test_registered_model_flag_adds_reasoning_effort_none_without_identity_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete_chat_message, payloads = _capture_chat_completions(
        monkeypatch,
        provider_id="gateway-x",
        response=_OkResponse(),
        models=[{"name": "vendor/chat-x", "reasoning_effort_none_on_disable": True}],
    )

    await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="vendor/chat-x",
        options={"temperature": 0, "max_tokens": 512, "model_effort": "disable"},
        cfg=SimpleNamespace(llm_api_key="sk", llm_model="vendor/chat-x", chat_timeout_sec=10.0),
        base_url="https://provider.example/v1",
        api_key="sk",
        task="repeater.semantic_style",
        provider_id="gateway-x",
    )

    assert payloads[0]["thinking"] == {"type": "disabled"}
    assert payloads[0]["reasoning_effort"] == "none"
    assert "stream" not in payloads[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_id", "model", "effort"),
    [
        ("deepseek-test", "deepseek-v4.1-flash", None),
        ("cpa", "deepseek-v4.1-flash", None),
        ("cpa", "deepseek-v4-flash", None),
        ("cpa", "deepseek-v4.1-flash", "high"),
        ("cpa", "deepseek-v4.1-flash", "enable"),
    ],
)
async def test_reasoning_effort_none_requires_model_opt_in(
    monkeypatch: pytest.MonkeyPatch, provider_id: str, model: str, effort: str | None
) -> None:
    complete_chat_message, payloads = _capture_chat_completions(
        monkeypatch, provider_id=provider_id, response=_OkResponse()
    )
    options: dict = {"temperature": 0, "max_tokens": 512}
    if effort:
        options["model_effort"] = effort

    await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model=model,
        options=options,
        cfg=SimpleNamespace(llm_api_key="sk", llm_model=model, chat_timeout_sec=10.0),
        base_url="https://provider.example/v1",
        api_key="sk",
        task="repeater.semantic_style",
        provider_id=provider_id,
    )

    assert payloads[0].get("reasoning_effort") != "none"


@pytest.mark.asyncio
async def test_reasoning_effort_none_flag_is_scoped_to_exact_registered_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = [
        {"name": "shared-model", "reasoning_effort_none_on_disable": True},
        {"name": "sibling-model", "reasoning_effort_none_on_disable": False},
    ]
    complete_chat_message, payloads = _capture_chat_completions(
        monkeypatch, provider_id="gateway", response=_OkResponse(), models=models
    )

    for model in ("shared-model", "sibling-model"):
        await complete_chat_message(
            [{"role": "user", "content": "hi"}],
            model=model,
            options={"model_effort": "disable"},
            cfg=SimpleNamespace(llm_api_key="sk", llm_model=model, chat_timeout_sec=10.0),
            base_url="https://provider.example/v1",
            api_key="sk",
            task="repeater.semantic_style",
            provider_id="gateway",
        )

    assert payloads[0]["thinking"] == {"type": "disabled"}
    assert payloads[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in payloads[1]


@pytest.mark.asyncio
async def test_explicit_disable_still_queries_provider_model_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import providers_store

    complete_chat_message, payloads = _capture_chat_completions(
        monkeypatch,
        provider_id="gateway",
        response=_OkResponse(),
        models=[{"name": "shared-model", "reasoning_effort_none_on_disable": True}],
    )
    calls: list[str] = []

    def tracking_find_provider(pid: str, **_kwargs):
        calls.append(pid)
        return {"id": pid, "models": [{"name": "shared-model", "reasoning_effort_none_on_disable": True}]}

    monkeypatch.setattr(providers_store, "find_provider", tracking_find_provider)
    monkeypatch.setattr("pallas.product.llm.provider_client.provider_daily_budget_ok", lambda _pid: True)

    await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="shared-model",
        options={"model_effort": "disable"},
        cfg=SimpleNamespace(llm_api_key="sk", llm_model="shared-model", chat_timeout_sec=10.0),
        base_url="https://provider.example/v1",
        api_key="sk",
        task="repeater.semantic_style",
        provider_id="gateway",
    )

    assert calls == ["gateway"]
    assert payloads[0]["reasoning_effort"] == "none"


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, OSError])
async def test_model_flag_read_error_blocks_http(monkeypatch: pytest.MonkeyPatch, error_type) -> None:
    complete_chat_message, payloads = _capture_chat_completions(
        monkeypatch, provider_id="gateway", response=_OkResponse()
    )
    error = error_type("provider configuration unavailable")

    def fail_find_provider(_pid):
        raise error

    monkeypatch.setattr("pallas.product.llm.providers_store.find_provider", fail_find_provider)
    monkeypatch.setattr("pallas.product.llm.provider_client.provider_daily_budget_ok", lambda _pid: True)

    with pytest.raises(error_type) as excinfo:
        await complete_chat_message(
            [{"role": "user", "content": "hi"}],
            model="shared-model",
            options={"model_effort": "disable"},
            cfg=SimpleNamespace(llm_api_key="sk", llm_model="shared-model", chat_timeout_sec=10.0),
            base_url="https://provider.example/v1",
            api_key="sk",
            provider_id="gateway",
        )

    assert excinfo.value is error
    assert payloads == []


@pytest.mark.asyncio
async def test_reasoning_effort_none_flag_does_not_cross_provider_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from pallas.product.llm.provider_client import complete_chat_message
    from pallas.product.llm.providers_store import clear_providers_store_cache, save_providers_document

    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "primary",
                "base_url": "https://primary.example/v1",
                "api_key": "sk-primary",
                "default_model": "shared-flash",
                "model_effort": "disable",
                "models": [{"name": "shared-flash"}],
            },
            {
                "id": "backup",
                "base_url": "https://backup.example/v1",
                "api_key": "sk-backup",
                "default_model": "shared-flash",
                "model_effort": "disable",
                "models": [{"name": "shared-flash", "reasoning_effort_none_on_disable": True}],
            },
        ],
        "routing": {"tasks": {"llm_chat": "primary"}, "task_backups": {"llm_chat": "backup"}},
    })
    clear_providers_store_cache()

    payloads: list[dict] = []

    class FakeClient:
        async def post(self, _url, *, json=None, **_kwargs):
            payloads.append(json)
            if len(payloads) == 1:
                return SimpleNamespace(status_code=500, headers={}, content=b"", text="upstream failed")
            return _OkResponse()

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr("pallas.product.llm.provider_client.get_llm_shared_httpx_client", fake_client)
    monkeypatch.setattr("pallas.product.llm.availability.llm_calls_enabled", lambda cfg=None: True)

    await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="",
        options={"temperature": 0, "max_tokens": 512},
        cfg=SimpleNamespace(llm_chat_enabled=True, llm_api_key="", chat_timeout_sec=10.0),
        task="llm_chat",
    )

    assert len(payloads) == 2
    assert payloads[0]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payloads[0]
    assert payloads[1]["thinking"] == {"type": "disabled"}
    assert payloads[1]["reasoning_effort"] == "none"
    clear_providers_store_cache()
