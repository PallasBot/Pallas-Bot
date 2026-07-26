"""chat.reply 通道：动作与开口拆分。"""

from __future__ import annotations

from typing import Any

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.tool_loop import (
    complete_with_tool_loop,
    resolve_visible_reply_after_tools,
    tool_names_from_schemas,
)
from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, clear_tool_registry, register_tool
from pallas.product.llm.tools.reply import CHAT_REPLY_NAME, extract_chat_reply_text, register_reply_tools


@pytest.fixture(autouse=True)
def reset_tools() -> None:
    reset_llm_tools_bootstrap_for_tests()
    yield
    reset_llm_tools_bootstrap_for_tests()


def test_resolve_visible_reply_prefers_chat_reply() -> None:
    text, source = resolve_visible_reply_after_tools(
        freeform_content="已经派发指令去画了",
        reply_texts=["房开了"],
        side_effect_ok=True,
        tool_call_count=2,
    )
    assert text == "房开了"
    assert source == "chat.reply"


def test_resolve_visible_reply_suppresses_meta_chat_reply() -> None:
    text, source = resolve_visible_reply_after_tools(
        freeform_content="",
        reply_texts=["整了个打工人表情，大伙品品"],
        side_effect_ok=True,
        tool_call_count=2,
    )
    assert text == ""
    assert source == "silence_after_side_effect"


def test_resolve_visible_reply_silence_after_side_effect() -> None:
    text, source = resolve_visible_reply_after_tools(
        freeform_content="已经派发指令去画了",
        reply_texts=[],
        side_effect_ok=True,
        tool_call_count=1,
    )
    assert text == ""
    assert source == "silence_after_side_effect"


def test_resolve_visible_reply_keeps_query_generate() -> None:
    text, source = resolve_visible_reply_after_tools(
        freeform_content="没查到这名干员",
        reply_texts=[],
        side_effect_ok=False,
        tool_call_count=1,
    )
    assert text == "没查到这名干员"
    assert source == "generate"


def test_extract_chat_reply_text() -> None:
    assert extract_chat_reply_text({"ok": True, "result": {"text": "来了", "visible_reply": True}}) == "来了"
    assert extract_chat_reply_text({"ok": True, "result": {"text": "", "silent": True}}) == ""
    assert extract_chat_reply_text({"ok": False, "error": "x"}) is None
    assert (
        extract_chat_reply_text({"ok": True, "result": {"text": "整了个打工人表情，大伙品品", "visible_reply": True}})
        == ""
    )


@pytest.mark.asyncio
async def test_chat_reply_handler_suppresses_meta() -> None:
    from pallas.product.llm.tools.reply import handle_chat_reply

    result = await handle_chat_reply({"text": "整了个打工人表情，大伙品品"})
    assert result["ok"] is True
    assert result["result"]["silent"] is True
    assert result["result"]["text"] == ""


def _register_side_effect_tool() -> None:
    clear_tool_registry()
    register_reply_tools()

    async def side_handler(args: dict, ctx=None):
        del args, ctx
        return {"ok": True, "result": {"dispatched": True}}

    register_tool(
        LlmToolSpec(
            name="demo.act",
            description="副作用动作",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=side_handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
        )
    )


@pytest.mark.asyncio
async def test_tool_loop_side_effect_discards_freeform(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_side_effect_tool()
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
                        "function": {"name": "demo.act", "arguments": "{}"},
                    }
                ],
            }
        second_tools.append(tools)
        return {"role": "assistant", "content": "已经派发指令去画了，等结果出来看看是不是我本人。"}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)

    cfg = LlmConfig(
        llm_runtime="bot_kernel",
        llm_base_url="http://example.test/v1",
        llm_model="demo",
        llm_tools_enabled=True,
        llm_tools_max_rounds=3,
    )
    content, assistant = await complete_with_tool_loop(
        system_prompt="sys",
        messages=[{"role": "user", "content": "画一张牛"}],
        metadata={
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "demo.act"}}],
            "bot_id": 1,
            "user_id": 2,
            "group_id": 3,
        },
        cfg=cfg,
    )
    assert content == ""
    trace = assistant.get("_agent_trace") or {}
    assert trace.get("reply_source") == "silence_after_side_effect"
    assert CHAT_REPLY_NAME in (trace.get("activated_tools") or [])
    names = set(tool_names_from_schemas(second_tools[0] or [])) if second_tools else set()
    assert "chat__reply" in names or CHAT_REPLY_NAME in names


@pytest.mark.asyncio
async def test_tool_loop_side_effect_uses_chat_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    _register_side_effect_tool()
    calls = {"n": 0}

    async def fake_complete(messages, *, model, options=None, tools=None, cfg=None, **_kwargs):
        del messages, model, options, tools, cfg
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "demo.act", "arguments": "{}"},
                    }
                ],
            }
        if calls["n"] == 2:
            return {
                "role": "assistant",
                "content": "自由文本应被忽略",
                "tool_calls": [
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {
                            "name": "chat__reply",
                            "arguments": '{"text":"房开了，想玩的加一下。"}',
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "又一段自由文本"}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)

    cfg = LlmConfig(
        llm_runtime="bot_kernel",
        llm_base_url="http://example.test/v1",
        llm_model="demo",
        llm_tools_enabled=True,
        llm_tools_max_rounds=4,
    )
    content, assistant = await complete_with_tool_loop(
        system_prompt="sys",
        messages=[{"role": "user", "content": "玩玩谁是卧底"}],
        metadata={
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "demo.act"}}],
            "bot_id": 1,
            "user_id": 2,
            "group_id": 3,
        },
        cfg=cfg,
    )
    assert content == "房开了，想玩的加一下。"
    trace = assistant.get("_agent_trace") or {}
    assert trace.get("reply_source") == "chat.reply"
    assert calls["n"] == 3
