"""Bot 内核 LLM：provider_client / tool_loop / submit 分支。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pallas.product.llm.provider_client import chat_completions_url, complete_chat_message
from pallas.product.llm.tool_loop import complete_with_tool_loop, parse_tool_arguments

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.submit_gate import assess_llm_kernel_submit_gate, user_message_for_submit_status


def test_chat_completions_url_normalizes_v1() -> None:
    assert chat_completions_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1/chat/completions"
    assert chat_completions_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1/chat/completions"


def test_parse_tool_arguments_json() -> None:
    assert parse_tool_arguments('{"name":"amiya"}') == {"name": "amiya"}
    assert parse_tool_arguments({"x": 1}) == {"x": 1}
    assert parse_tool_arguments("not-json") == {}


def test_kernel_submit_gate_requires_provider() -> None:
    cfg = LlmConfig(llm_runtime="bot_kernel", llm_base_url="", llm_model="")
    result = assess_llm_kernel_submit_gate(cfg)
    assert result.allowed is False
    assert result.status == "provider_not_configured"
    assert user_message_for_submit_status("provider_not_configured")

    ok = assess_llm_kernel_submit_gate(
        LlmConfig(llm_runtime="bot_kernel", llm_base_url="http://127.0.0.1:11434/v1", llm_model="qwen2.5:7b")
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

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any] | None = None, headers: dict | None = None) -> FakeResponse:
            assert url.endswith("/chat/completions")
            assert json is not None
            assert json["model"] == "demo"
            return FakeResponse()

    monkeypatch.setattr("pallas.product.llm.provider_client.httpx.AsyncClient", FakeClient)
    cfg = LlmConfig(
        llm_runtime="bot_kernel",
        llm_base_url="http://example.test/v1",
        llm_api_key="sk-test",
        llm_model="demo",
        chat_timeout_sec=5.0,
    )
    message = await complete_chat_message(
        [{"role": "user", "content": "hi"}],
        model="demo",
        cfg=cfg,
    )
    assert message["content"] == "你好"


@pytest.mark.asyncio
async def test_tool_loop_one_round(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def fake_complete(messages, *, model, options=None, tools=None, cfg=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "demo.echo", "arguments": '{"text":"ok"}'},
                    }
                ],
            }
        return {"role": "assistant", "content": "最终回复"}

    async def fake_execute(name, arguments, *, context=None):
        assert name == "demo.echo"
        return {"ok": True, "result": {"echo": arguments}}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)
    monkeypatch.setattr("pallas.product.llm.tool_loop.execute_tool_async", fake_execute)

    cfg = LlmConfig(
        llm_runtime="bot_kernel",
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
            "bot_id": 1,
            "user_id": 2,
            "group_id": 3,
        },
        cfg=cfg,
    )
    assert content == "最终回复"
    assert calls["n"] == 2
    assert assistant.get("_agent_trace", {}).get("tool_call_count") == 1


@pytest.mark.asyncio
async def test_submit_chat_task_kernel_schedules_deliver(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_config_cache()
    delivered: list[tuple[str, str, str]] = []

    cfg = LlmConfig(
        llm_runtime="bot_kernel",
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
