from __future__ import annotations

from typing import Any

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.tool_loop import complete_with_tool_loop, tool_names_from_schemas
from pallas.product.llm.tools.activation_cache import activated_tool_names, clear_activation_cache_for_tests
from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.discovery import TOOLS_FIND_NAME, register_discovery_tools
from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, clear_tool_registry, register_tool


@pytest.fixture(autouse=True)
def reset_tools() -> None:
    reset_llm_tools_bootstrap_for_tests()
    clear_activation_cache_for_tests()
    yield
    reset_llm_tools_bootstrap_for_tests()
    clear_activation_cache_for_tests()


@pytest.mark.asyncio
async def test_tools_find_activates_deferred_tool_for_next_round(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_tool_registry()
    register_discovery_tools()

    async def deferred_handler(args: dict, ctx=None):
        del args, ctx
        return {"ok": True, "result": {"echo": "pong"}}

    register_tool(
        LlmToolSpec(
            name="demo.deferred_ping",
            description="冷门演示工具",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=deferred_handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}),
            hints=frozenset({"冷门演示"}),
            visibility="deferred",
        )
    )

    calls = {"n": 0}
    second_tools: list[Any] = []

    async def fake_complete(messages, *, model, options=None, tools=None, cfg=None, **_kwargs):
        del messages, model, options, cfg
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": TOOLS_FIND_NAME, "arguments": '{"query":"冷门演示"}'},
                    }
                ],
            }
        if calls["n"] == 2:
            second_tools.append(tools)
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {"name": "demo.deferred_ping", "arguments": "{}"},
                    }
                ],
            }
        return {"role": "assistant", "content": "好了"}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)

    content, assistant = await complete_with_tool_loop(
        system_prompt="sys",
        messages=[{"role": "user", "content": "找冷门演示"}],
        metadata={
            "task": "llm_chat",
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": TOOLS_FIND_NAME}}],
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
        },
        cfg=LlmConfig(
            llm_runtime="bot_kernel",
            llm_base_url="http://example.test/v1",
            llm_model="demo",
            llm_tools_enabled=True,
            llm_tools_max_rounds=4,
        ),
    )

    assert content == "好了"
    names = set(tool_names_from_schemas(second_tools[0] or [])) if second_tools else set()
    assert "demo__deferred_ping" in names or "demo.deferred_ping" in names
    assert "demo.deferred_ping" in ((assistant.get("_agent_trace") or {}).get("activated_tools") or [])
    assert "demo.deferred_ping" in activated_tool_names(1, 2, 3)
