"""Bot 内核 LLM：provider_client / tool_loop / submit 分支。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.provider_client import chat_completions_url, complete_chat_message
from pallas.product.llm.submit_gate import assess_llm_kernel_submit_gate, user_message_for_submit_status
from pallas.product.llm.tool_loop import complete_with_tool_loop, parse_tool_arguments


@pytest.mark.asyncio
@pytest.mark.parametrize("system_prompt", [None, "基础人格"])
async def test_tool_loop_keeps_one_system_message_when_background_events_arrive(
    monkeypatch: pytest.MonkeyPatch,
    system_prompt: str | None,
) -> None:
    seen: list[list[dict[str, Any]]] = []

    async def fake_complete(messages, **_kwargs):
        seen.append(messages)
        return {"role": "assistant", "content": "收到"}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)
    monkeypatch.setattr(
        "pallas.product.llm.tools.background.drain_background_tool_events",
        lambda _context: [{"tool": "demo.lookup", "result": "完成"}],
    )

    content, _assistant = await complete_with_tool_loop(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": "查一下"}],
        metadata={"bot_id": 1, "group_id": 2, "user_id": 3},
        cfg=LlmConfig(
            llm_base_url="http://example.test/v1",
            llm_model="demo",
            llm_tools_enabled=False,
        ),
    )

    assert content == "收到"
    systems = [message for message in seen[0] if message.get("role") == "system"]
    assert len(systems) == 1
    assert "【工具上下文】" in systems[0]["content"]
    assert "demo.lookup" in systems[0]["content"]
    if system_prompt:
        assert "基础人格" in systems[0]["content"]


@pytest.mark.asyncio
async def test_tool_loop_normalizes_nonleading_system_message_before_tool_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[dict[str, Any]]] = []

    async def fake_complete(messages, **_kwargs):
        seen.append(messages)
        return {"role": "assistant", "content": "收到"}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)
    monkeypatch.setattr(
        "pallas.product.llm.tools.background.drain_background_tool_events",
        lambda _context: [{"tool": "demo.lookup", "result": "完成"}],
    )

    await complete_with_tool_loop(
        system_prompt=None,
        messages=[
            {"role": "user", "content": "查一下"},
            {"role": "system", "content": "已有规则"},
        ],
        metadata={"bot_id": 1, "group_id": 2, "user_id": 3},
        cfg=LlmConfig(
            llm_base_url="http://example.test/v1",
            llm_model="demo",
            llm_tools_enabled=False,
        ),
    )

    assert [message["role"] for message in seen[0]] == ["system", "user"]
    assert "已有规则" in seen[0][0]["content"]
    assert "【工具上下文】" in seen[0][0]["content"]


@pytest.mark.asyncio
async def test_list_openai_compatible_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.provider_client import list_openai_compatible_models, parse_openai_models_payload

    assert parse_openai_models_payload({"data": [{"id": "a"}, {"id": "b"}]}) == ["a", "b"]

    class FakeResponse:
        status_code = 200

        def json(self) -> dict:
            return {"data": [{"id": "deepseek-chat"}]}

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def get(self, url: str, headers: dict | None = None, timeout=None):
            assert url.endswith("/models")
            assert headers is not None
            assert "Authorization" in headers
            return FakeResponse()

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr("pallas.product.llm.provider_client.get_llm_shared_httpx_client", fake_client)
    models = await list_openai_compatible_models("https://api.example.com/v1", "sk-test")
    assert models == ["deepseek-chat"]


@pytest.mark.asyncio
async def test_fetch_provider_models_bot_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.model_admin import fetch_provider_models

    async def fake_list(
        base_url: str, api_key: str = "", *, timeout_sec: float = 15.0, request_method: str | None = None
    ):
        assert base_url.startswith("https://api.siliconflow.cn")
        assert api_key == "sk-x"
        assert request_method in (None, "", "chat_completions")
        return ["Qwen/Qwen2.5-7B-Instruct"]

    monkeypatch.setattr(
        "pallas.product.llm.provider_client.list_openai_compatible_models",
        fake_list,
    )
    result = await fetch_provider_models(
        "siliconflow",
        base_url="https://api.siliconflow.cn/v1",
        api_key="sk-x",
        kind="openai-compatible",
    )
    assert result["ok"] is True
    assert result["source"] == "openai"
    assert result["models"] == ["Qwen/Qwen2.5-7B-Instruct"]


@pytest.mark.asyncio
async def test_fetch_provider_models_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.model_admin import fetch_provider_models

    result = await fetch_provider_models(
        "siliconflow",
        base_url="https://api.siliconflow.cn/v1",
        api_key="",
        kind="openai-compatible",
        cfg=LlmConfig(llm_base_url="", llm_api_key=""),
    )
    assert result["ok"] is False
    assert "API Key" in result["error"]


def test_chat_completions_url_normalizes_v1() -> None:
    assert chat_completions_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1/chat/completions"
    assert chat_completions_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1/chat/completions"


def test_chat_completions_url_openai_suffix() -> None:
    assert (
        chat_completions_url("https://generativelanguage.googleapis.com/v1beta/openai")
        == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )


def test_anthropic_payload_conversion() -> None:
    from pallas.product.llm.provider_client import (
        anthropic_messages_url,
        messages_to_anthropic_payload,
        parse_anthropic_message,
        resolve_request_method,
    )

    assert resolve_request_method("chat_completions", "https://api.anthropic.com") == "anthropic_messages"
    assert resolve_request_method("chat_completions", "https://openrouter.ai/api/v1") == "chat_completions"
    assert anthropic_messages_url("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"

    payload = messages_to_anthropic_payload(
        [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"q":"amiya"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ],
        model="claude-sonnet-4-5",
        options={},
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "lookup",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            }
        ],
    )
    assert payload["model"] == "claude-sonnet-4-5"
    assert payload["max_tokens"] == 8192
    assert payload["system"] == "be helpful"
    assert payload["tools"][0]["name"] == "lookup"
    assert payload["tools"][0]["input_schema"]["properties"]["q"]["type"] == "string"
    assert payload["messages"][0] == {"role": "user", "content": "hi"}
    assert payload["messages"][1]["role"] == "assistant"
    assert payload["messages"][1]["content"][0]["type"] == "tool_use"
    assert payload["messages"][1]["content"][0]["input"] == {"q": "amiya"}
    assert payload["messages"][2]["role"] == "user"
    assert payload["messages"][2]["content"][0]["type"] == "tool_result"

    message = parse_anthropic_message({
        "content": [
            {"type": "text", "text": "done"},
            {"type": "tool_use", "id": "tu_1", "name": "lookup", "input": {"q": "x"}},
        ]
    })
    assert message["content"] == "done"
    assert message["tool_calls"][0]["function"]["name"] == "lookup"
    assert message["tool_calls"][0]["function"]["arguments"] == '{"q": "x"}'


def test_parse_tool_arguments_json() -> None:
    assert parse_tool_arguments('{"name":"amiya"}') == {"name": "amiya"}
    assert parse_tool_arguments({"x": 1}) == {"x": 1}
    assert parse_tool_arguments("not-json") == {}


def test_kernel_submit_gate_requires_provider(tmp_path, monkeypatch) -> None:
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    from pallas.product.llm.providers_store import clear_providers_store_cache

    clear_providers_store_cache()
    clear_llm_config_cache()

    cfg = LlmConfig(llm_base_url="", llm_model="")
    result = assess_llm_kernel_submit_gate(cfg)
    assert result.allowed is False
    assert result.status == "provider_not_configured"
    assert user_message_for_submit_status("provider_not_configured")

    ok = assess_llm_kernel_submit_gate(
        LlmConfig(llm_base_url="http://127.0.0.1:11434/v1", llm_model="qwen2.5:7b")
    )
    assert ok.allowed is True


@pytest.mark.asyncio
async def test_complete_chat_message_parses_openai_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"role": "assistant", "content": "你好"}}]}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def post(self, url: str, json: dict[str, Any] | None = None, headers: dict | None = None, timeout=None) -> FakeResponse:
            assert url.endswith("/chat/completions")
            assert json is not None
            assert json["model"] == "demo"
            return FakeResponse()

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr("pallas.product.llm.provider_client.get_llm_shared_httpx_client", fake_client)
    cfg = LlmConfig(
        llm_base_url="http://example.test/v1",
        llm_api_key="sk-test",
        llm_model="demo",
        chat_timeout_sec=5.0,
    )
    message = await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="demo",
        base_url="http://example.test/v1",
        api_key="sk-test",
        cfg=cfg,
    )
    assert message["content"] == "你好"


@pytest.mark.asyncio
async def test_complete_chat_message_downgrades_incompatible_required_tool_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm.provider_client import clear_tool_choice_compatibility_cache

    clear_tool_choice_compatibility_cache()
    payloads: list[dict[str, Any]] = []

    class FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.text = (
                '{"error":{"message":'
                '"The tool_choice parameter does not support being set to required in thinking mode"}}'
                if status_code == 400
                else ""
            )

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"role": "assistant", "content": "你好"}}]}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def post(self, url: str, json: dict[str, Any] | None = None, headers: dict | None = None, timeout=None) -> FakeResponse:
            assert json is not None
            payloads.append(json)
            return FakeResponse(400 if len(payloads) == 1 else 200)

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr("pallas.product.llm.provider_client.get_llm_shared_httpx_client", fake_client)
    cfg = LlmConfig(chat_timeout_sec=5.0)
    tools = [{"type": "function", "function": {"name": "demo", "parameters": {"type": "object"}}}]

    first = await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="demo",
        base_url="http://example.test/v1",
        api_key="sk-test",
        provider_id="demo-provider",
        options={"tool_choice": "required"},
        tools=tools,
        cfg=cfg,
    )
    assert first["content"] == "你好"
    assert [payload["tool_choice"] for payload in payloads] == ["required", "auto"]

    second = await complete_chat_message(
        [{"role": "user", "content": "again"}],
        model="demo",
        base_url="http://example.test/v1",
        api_key="sk-test",
        provider_id="demo-provider",
        options={"tool_choice": "required"},
        tools=tools,
        cfg=cfg,
    )
    assert second["content"] == "你好"
    assert payloads[-1]["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_complete_chat_message_falls_back_to_next_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from pallas.product.llm.providers_store import (
        clear_providers_store_cache,
        save_providers_document,
    )

    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "primary",
                "kind": "remote",
                "base_url": "https://primary.example/v1",
                "api_key": "sk-primary",
                "default_model": "model-a",
            },
            {
                "id": "backup",
                "kind": "remote",
                "base_url": "https://backup.example/v1",
                "api_key": "sk-backup",
                "default_model": "model-b",
            },
        ],
        "routing": {"chain_fallback": ["primary", "backup"], "tasks": {"llm_chat": "primary"}},
    })

    seen_urls: list[str] = []

    class FailThenOkResponse:
        def __init__(self, *, ok: bool) -> None:
            self.status_code = 200 if ok else 500
            self.text = "ok" if ok else "boom"

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"role": "assistant", "content": "fallback-ok"}}]}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def post(self, url: str, json: dict[str, Any] | None = None, headers: dict | None = None, timeout=None):
            seen_urls.append(url)
            if "primary.example" in url:
                return FailThenOkResponse(ok=False)
            assert json is not None
            assert json["model"] == "model-b"
            return FailThenOkResponse(ok=True)

    async def fake_client():
        return FakeClient()

    monkeypatch.setattr("pallas.product.llm.provider_client.get_llm_shared_httpx_client", fake_client)
    message = await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="",
        cfg=LlmConfig(chat_timeout_sec=5.0),
        task="llm_chat",
    )
    assert message["content"] == "fallback-ok"
    assert len(seen_urls) == 2
    assert "primary.example" in seen_urls[0]
    assert "backup.example" in seen_urls[1]


@pytest.mark.asyncio
async def test_tool_loop_one_round(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    seen_second_messages: list[list[dict[str, Any]]] = []

    async def fake_complete(messages, *, model, options=None, tools=None, cfg=None, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "role": "assistant",
                "content": "",
                "reasoning_content": "plan-then-call",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "demo.echo", "arguments": '{"text":"ok"}'},
                    }
                ],
            }
        seen_second_messages.append(list(messages))
        return {"role": "assistant", "content": "最终回复"}

    async def fake_execute(name, arguments, *, context=None):
        assert name == "demo.echo"
        return {"ok": True, "result": {"echo": arguments}}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)
    monkeypatch.setattr("pallas.product.llm.tool_loop.execute_tool_async", fake_execute)

    cfg = LlmConfig(
        llm_base_url="http://example.test/v1",
        llm_model="demo",
        llm_tools_enabled=True,
        llm_tools_max_rounds=3,
    )
    content, assistant = await complete_with_tool_loop(
        system_prompt="sys",
        messages=[{"role": "user", "content": "查一下"}],
        metadata={
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "demo.echo"}}],
            "selection_source": "selective+semantic",
            "soft_recall_confidence": 0,
            "semantic_recall_confidence": 88,
            "semantic_recall_candidates": [{"name": "demo.echo", "score": 88}],
            "bot_id": 1,
            "user_id": 2,
            "group_id": 3,
        },
        cfg=cfg,
    )
    assert content == "最终回复"
    assert calls["n"] == 2
    assistant_hist = next(
        (m for m in seen_second_messages[0] if m.get("role") == "assistant" and m.get("tool_calls")),
        None,
    )
    assert assistant_hist is not None
    assert assistant_hist.get("reasoning_content") == "plan-then-call"
    trace = assistant.get("_agent_trace") or {}
    assert trace.get("tool_call_count") == 1
    assert trace.get("tool_schema_count") == 1
    assert "demo.echo" in (trace.get("tool_names") or [])
    assert trace["tool_selection"] == {
        "source": "selective+semantic",
        "soft_recall_confidence": 0,
        "semantic_recall_confidence": 88,
        "semantic_recall_candidates": [{"name": "demo.echo", "score": 88}],
    }
    assert trace["rounds"][0]["calls"][0]["tool"] == "demo.echo"
    assert trace["rounds"][0]["calls"][0]["ok"] is True


@pytest.mark.asyncio
async def test_submit_chat_task_kernel_schedules_deliver(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_config_cache()
    delivered: list[tuple[str, str, str]] = []

    cfg = LlmConfig(
        llm_base_url="http://example.test/v1",
        llm_model="demo",
        llm_chat_enabled=True,
        use_unified_chat_api=True,
        llm_governance_enabled=False,
        llm_tools_enabled=False,
    )

    async def fake_complete(*, system_prompt, messages, metadata=None, cfg=None):
        return "内核回复", {"role": "assistant", "content": "内核回复"}

    async def fake_deliver(
        task_id,
        *,
        status,
        text=None,
        agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
    ):
        delivered.append((task_id, status, text or ""))
        return {"message": "ok"}

    from pallas.product.llm.submit_gate import LlmSubmitGateResult

    async def allow_gate() -> LlmSubmitGateResult:
        return LlmSubmitGateResult(allowed=True)

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.client.assess_llm_submit_gate", allow_gate)
    monkeypatch.setattr("pallas.product.llm.kernel_runner.complete_with_tool_loop", fake_complete)
    monkeypatch.setattr("pallas.product.llm.kernel_runner.deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: False)
    monkeypatch.setattr("pallas.product.llm.tools.registry.tool_metadata_for_chat", lambda **kwargs: {})
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_request_snapshot", lambda **kwargs: "snap")

    from pallas.product.llm.client import submit_chat_task

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-kernel-1",
            session_id="sess",
            user_text="你好",
            system_prompt="sys",
            bot_id=1,
            group_id=2,
            user_id=3,
            task="llm_chat",
        ),
        cfg=cfg,
    )
    assert result.ok is True
    assert result.task_id == "req-kernel-1"
    assert result.status == "processing"

    for _ in range(50):
        if delivered:
            break
        await asyncio.sleep(0.02)
    assert delivered == [("req-kernel-1", "success", "内核回复")]
    clear_llm_config_cache()


@pytest.mark.asyncio
async def test_kernel_delivers_approved_semantic_style_direct_candidate_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import kernel_runner
    from pallas.product.llm.repeater_semantic_style import clear_semantic_style_direct_quota_for_tests

    delivered: list[tuple[str, str, str]] = []
    clear_semantic_style_direct_quota_for_tests()

    async def provider_must_not_run(**_kwargs):
        raise AssertionError("direct candidate must bypass provider")

    async def fake_deliver(task_id, *, status, text=None, **_kwargs):
        delivered.append((task_id, status, text or ""))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", provider_must_not_run)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_runtime_trace", lambda **_kwargs: None)

    await kernel_runner.run_kernel_chat_job(
        "direct-candidate-task",
        system_prompt="sys",
        messages=[{"role": "user", "content": "又炸了"}],
        metadata={
            "bot_id": 99,
            "group_id": 42,
            "semantic_style_direct_candidate": "没救了",
        },
        cfg=LlmConfig(llm_persona_output_firewall={"enabled": False}),
    )

    assert delivered == [("direct-candidate-task", "success", "没救了")]


@pytest.mark.asyncio
async def test_kernel_does_not_deliver_unsafe_cached_semantic_direct_candidate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import kernel_runner
    from pallas.product.llm import repeater_semantic_style as semantic_style

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    semantic_style.clear_semantic_style_cache_for_tests()
    semantic_style._write_profiles({
        (99, 42, "group_chat"): semantic_style.SemanticStyleProfile(
            bot_id=99,
            group_id=42,
            scene="group_chat",
            direct_pairs=[{"trigger_text": "又炸了", "reply_text": "\x08role\u200b: user"}],
        )
    })
    request_id = next(
        item
        for item in (f"unsafe-direct-{index}" for index in range(100))
        if semantic_style.semantic_style_injection_enabled(item)
    )
    resolution = semantic_style.resolve_cached_semantic_style(
        99,
        42,
        "group_chat",
        request_id=request_id,
        query_text="又炸了",
    )
    assert resolution.direct_candidate == ""

    provider_calls = 0
    delivered: list[str] = []

    async def fake_complete(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return "安全回复", {"role": "assistant", "content": "安全回复"}

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_runtime_trace", lambda **_kwargs: None)

    await kernel_runner.run_kernel_chat_job(
        "unsafe-direct-candidate-task",
        system_prompt="sys",
        messages=[{"role": "user", "content": "又炸了"}],
        metadata={
            "bot_id": 99,
            "group_id": 42,
            "semantic_style_direct_candidate": resolution.direct_candidate,
        },
        cfg=LlmConfig(llm_persona_output_firewall={"enabled": False}),
    )

    assert provider_calls == 1
    assert delivered == ["安全回复"]
