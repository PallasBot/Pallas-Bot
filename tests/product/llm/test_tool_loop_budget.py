from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.tool_loop import complete_with_tool_loop
from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, clear_tool_registry, register_tool


@pytest.fixture(autouse=True)
def reset_tools() -> None:
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()
    yield
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()


@pytest.mark.asyncio
async def test_duplicate_query_call_forces_final_answer_without_third_tool_call(monkeypatch) -> None:
    async def search(_args, _ctx=None):
        return {"ok": True, "result": {"count": 1, "items": [{"title": "命中"}]}}

    register_tool(
        LlmToolSpec(
            name="demo.search",
            description="查询资料",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            domains=frozenset({"demo"}),
            handler=search,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}),
        )
    )
    calls: list[object] = []

    async def fake_complete(messages, *, tools=None, **_kwargs):
        del messages
        calls.append(tools)
        if len(calls) <= 2:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"c{len(calls)}",
                        "type": "function",
                        "function": {"name": "demo__search", "arguments": '{"query":"相同"}'},
                    }
                ],
            }
        return {"role": "assistant", "content": "这是最终答案。"}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)
    content, assistant = await complete_with_tool_loop(
        system_prompt="sys",
        messages=[{"role": "user", "content": "查资料"}],
        metadata={
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "demo__search"}}],
            "bot_id": 1,
            "user_id": 2,
            "group_id": 3,
        },
        cfg=LlmConfig(llm_tools_enabled=True, llm_tools_max_rounds=4),
    )

    trace = assistant["_agent_trace"]
    assert content == "这是最终答案。"
    assert len(calls) == 3
    assert calls[-1] is None
    assert trace["duplicate_tool_call_blocked"] == 1
    assert trace["successful_query_call_count"] == 1
    assert trace["final_stage"] == "final_answer"
