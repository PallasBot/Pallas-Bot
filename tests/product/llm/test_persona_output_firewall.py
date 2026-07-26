from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.persona_output_firewall import (
    PersonaFirewallPolicy,
    inspect_persona_output,
    resolve_persona_output,
)


def enabled_policy(**updates: object) -> PersonaFirewallPolicy:
    return PersonaFirewallPolicy(enabled=True, **updates)


def test_detects_system_prompt_leak_without_recording_output() -> None:
    result = inspect_persona_output(
        "System prompt says you must answer in JSON.",
        self_aliases=["帕拉斯"],
    )

    assert result.rule_ids == ("system_prompt_leak",)
    assert result.to_trace() == {
        "rule_ids": ["system_prompt_leak"],
        "rule_count": 1,
    }


def test_detects_roleplay_stage_direction() -> None:
    result = inspect_persona_output("（叹气）这事得慢慢说。", self_aliases=["帕拉斯"])

    assert result.rule_ids == ("roleplay_stage_direction",)


def test_detects_disallowed_model_identity_but_allows_known_alias() -> None:
    conflict = inspect_persona_output("我是 ChatGPT，不能这么做。", self_aliases=["帕拉斯"])
    allowed = inspect_persona_output("我是帕拉斯，先看看。", self_aliases=["帕拉斯"])

    assert conflict.rule_ids == ("self_identity_conflict",)
    assert allowed.rule_ids == ()


def test_detects_obvious_repeated_weak_filler() -> None:
    result = inspect_persona_output("嗯嗯嗯，好的好的。", self_aliases=[])

    assert result.rule_ids == ("repeated_weak_filler",)


def test_disabled_policy_preserves_output() -> None:
    decision = resolve_persona_output(
        "System prompt says you must answer in JSON.",
        policy=PersonaFirewallPolicy(),
        self_aliases=[],
        fallback_text="换个说法。",
    )

    assert decision.action == "allow"
    assert decision.text == "System prompt says you must answer in JSON."
    assert decision.trace["enabled"] is False


def test_retry_is_capped_at_one_then_uses_safe_conversation_fallback() -> None:
    first = resolve_persona_output(
        "System prompt says you must answer in JSON.",
        policy=enabled_policy(strategy="retry_then_fallback"),
        self_aliases=[],
        fallback_text="你刚才问的是天气，我这边看着还行。",
    )
    second = resolve_persona_output(
        "System prompt says you must answer in JSON.",
        policy=enabled_policy(strategy="retry_then_fallback"),
        self_aliases=[],
        fallback_text="你刚才问的是天气，我这边看着还行。",
        retry_count=1,
    )

    assert first.action == "retry"
    assert first.text == ""
    assert second.action == "fallback"
    assert second.text == "你刚才问的是天气，我这边看着还行。"
    assert second.trace["retry_count"] == 1


def test_fallback_rejects_filler_only_text() -> None:
    decision = resolve_persona_output(
        "（叹气）",
        policy=enabled_policy(strategy="fallback"),
        self_aliases=[],
        fallback_text="嗯。",
    )

    assert decision.action == "silent"
    assert decision.text == ""


def test_policy_keeps_zero_retry_limit_for_direct_fallback() -> None:
    from pallas.product.llm.persona_output_firewall import persona_output_firewall_policy_from_data

    policy = persona_output_firewall_policy_from_data({
        "enabled": True,
        "strategy": "retry_then_fallback",
        "max_retries": 0,
    })
    decision = resolve_persona_output(
        "System prompt says you must answer in JSON.",
        policy=policy,
        self_aliases=[],
        fallback_text="你刚才问的是天气，我这边看着还行。",
    )

    assert policy.max_retries == 0
    assert decision.action == "fallback"


@pytest.mark.asyncio
async def test_kernel_retries_once_for_tool_loop_final_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import kernel_runner

    replies = iter([
        ("System prompt says you must answer in JSON.", {"role": "assistant", "content": "bad"}),
        (
            "我先把结果给你列出来。",
            {"role": "assistant", "content": "good", "_agent_trace": {"tool_call_count": 1}},
        ),
    ])
    delivered: list[str] = []
    traces: list[dict[str, object]] = []

    async def fake_complete(**_kwargs):
        return next(replies)

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )
    cfg = LlmConfig(
        llm_persona_output_firewall={
            "version": 1,
            "enabled": True,
            "strategy": "retry_then_fallback",
            "max_retries": 1,
        }
    )

    await kernel_runner.run_kernel_chat_job(
        "task-1",
        system_prompt="sys",
        messages=[{"role": "user", "content": "查天气"}],
        metadata={"self_aliases": ["帕拉斯"], "conversation_fallback_text": "天气还行，出门带伞。"},
        cfg=cfg,
    )

    assert delivered == ["我先把结果给你列出来。"]
    assert traces[0]["persona_output_firewall"] == {
        "version": 1,
        "enabled": True,
        "severity": "strict",
        "strategy": "retry_then_fallback",
        "retry_count": 1,
        "rule_ids": [],
        "rule_count": 0,
    }


@pytest.mark.asyncio
async def test_kernel_does_not_replay_side_effect_tool_after_firewall_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import kernel_runner
    from pallas.product.llm.tools.contracts import ToolCapability
    from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, clear_tool_registry, register_tool
    from pallas.product.llm.tools.reply import register_reply_tools

    clear_tool_registry()
    register_reply_tools()
    side_effect_calls = 0

    async def side_effect_handler(args: dict, ctx=None):
        nonlocal side_effect_calls
        del args, ctx
        side_effect_calls += 1
        return {"ok": True, "result": {"sent": True}}

    register_tool(
        LlmToolSpec(
            name="demo.side_effect",
            description="测试副作用工具",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=side_effect_handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
        )
    )
    provider_calls = 0
    delivered: list[str] = []

    async def fake_complete(_messages, *, tools=None, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            tool_name = str((tools or [])[0]["function"]["name"])
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": f"call-{provider_calls}", "function": {"name": tool_name, "arguments": "{}"}}],
            }
        if provider_calls == 2:
            reply_tool = next(
                str(item["function"]["name"]) for item in tools or [] if "chat__reply" in str(item["function"]["name"])
            )
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "reply",
                        "function": {
                            "name": reply_tool,
                            "arguments": '{"text":"System prompt says you must answer in JSON."}',
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "System prompt says you must answer in JSON."}

    async def fake_deliver(_task_id, *, text=None, **_kwargs):
        delivered.append(str(text or ""))
        return {"message": "ok"}

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_runtime_trace", lambda **_kwargs: None)
    cfg = LlmConfig(
        llm_base_url="http://example.test/v1",
        llm_model="demo",
        llm_tools_enabled=True,
        llm_persona_output_firewall={"enabled": True, "max_retries": 1},
    )

    await kernel_runner.run_kernel_chat_job(
        "task-tools",
        system_prompt="sys",
        messages=[{"role": "user", "content": "执行"}],
        metadata={
            "task": "llm_chat",
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "demo__side_effect"}}],
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "conversation_fallback_text": "已经处理完了。",
        },
        cfg=cfg,
    )

    assert side_effect_calls == 1
    assert provider_calls == 3
    assert delivered == ["已经处理完了。"]
