from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_telemetry_metadata_allows_only_turn_linkage() -> None:
    from pallas.product.llm.turn_telemetry import telemetry_metadata

    assert telemetry_metadata({"turn_id": "turn-1", "prompt": "secret", "user_text": "原文"}) == {"turn_id": "turn-1"}
    assert telemetry_metadata({"prompt": "secret"}) == {}


@pytest.mark.asyncio
async def test_submit_chat_task_is_retired_and_never_reaches_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm.client import submit_chat_task
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.models import ChatSubmitRequest

    submit_kernel = AsyncMock()
    monkeypatch.setattr("pallas.product.llm.kernel_runner.submit_kernel_llm_chat_task", submit_kernel, raising=False)

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="request-1",
            session_id="session-1",
            user_text="短句",
            system_prompt="system",
            task="llm_chat",
            llm_rewrite_metadata={"turn_id": "turn-1", "prompt": "secret", "reply_target": "fact"},
        ),
        cfg=LlmConfig(llm_chat_enabled=True, llm_base_url="http://127.0.0.1:9/v1", llm_model="test-model"),
    )

    assert result.ok is False
    assert result.status == "legacy_agent_retired"
    submit_kernel.assert_not_called()


@pytest.mark.asyncio
async def test_kernel_passes_turn_linkage_into_tool_loop_without_rewriting_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.kernel_runner import run_kernel_chat_job

    seen: dict[str, object] = {}

    async def fake_complete_with_tool_loop(**kwargs):
        seen.update(kwargs["metadata"])
        return "收到", {"role": "assistant", "content": "收到"}

    monkeypatch.setattr(
        "pallas.product.llm.repeater_semantic_style.should_deliver_semantic_style_direct_candidate",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr("pallas.product.llm.kernel_runner.complete_with_tool_loop", fake_complete_with_tool_loop)
    monkeypatch.setattr(
        "pallas.product.llm.persona_output_firewall.persona_output_firewall_policy_from_data",
        lambda _data: SimpleNamespace(max_retries=0),
    )
    monkeypatch.setattr(
        "pallas.product.llm.persona_output_firewall.resolve_persona_output",
        lambda content, **_kwargs: SimpleNamespace(action="deliver", text=content, trace={}),
    )
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_chat_enabled=True),
    )
    monkeypatch.setattr(
        "pallas.product.llm.availability.get_llm_config",
        lambda: LlmConfig(llm_chat_enabled=True),
    )
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)

    async def scope_enabled(_bot_id, _group_id):
        return False

    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", scope_enabled)
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_runtime_trace", lambda **_kwargs: None)
    monkeypatch.setattr("pallas.product.llm.kernel_runner.deliver_llm_chat_result", AsyncMock())

    await run_kernel_chat_job(
        "request-1",
        system_prompt="system",
        messages=[{"role": "user", "content": "短句"}],
        metadata={"turn_id": "turn-1", "reply_target": "fact"},
        cfg=LlmConfig(llm_chat_enabled=True, llm_persona_output_firewall={}),
    )

    assert seen["turn_id"] == "turn-1"
    assert seen["reply_target"] == "fact"


@pytest.fixture(autouse=True)
def _historical_legacy_agent_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """历史内核测试：自研 agent 生成已全局退役；还原旧聊天 exit gate 以隔离纯算法断言。"""
    from pallas.product.llm import availability

    async def _old_gate(bot_id, group_id, *, captured_enabled=True):
        if not captured_enabled or not availability.llm_calls_enabled(availability.get_llm_config()):
            return "global_disabled_after_submit"
        if await availability.llm_plugin_disabled_for_scope(bot_id, group_id):
            return "scope_disabled_after_submit"
        if not availability.llm_calls_enabled(availability.get_llm_config()):
            return "global_disabled_after_submit"
        return ""

    monkeypatch.setattr(availability, "llm_chat_exit_gate_reason", _old_gate)
    from pallas.product.llm import kernel_runner

    monkeypatch.setattr(kernel_runner, "llm_chat_exit_gate_reason", _old_gate)
