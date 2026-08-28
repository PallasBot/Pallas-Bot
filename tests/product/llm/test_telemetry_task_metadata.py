from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_telemetry_metadata_allows_only_turn_linkage() -> None:
    from pallas.product.llm.turn_telemetry import telemetry_metadata

    assert telemetry_metadata({"turn_id": "turn-1", "prompt": "secret", "user_text": "原文"}) == {"turn_id": "turn-1"}
    assert telemetry_metadata({"prompt": "secret"}) == {}


@pytest.mark.asyncio
async def test_submit_chat_task_keeps_behavior_metadata_but_exposes_safe_telemetry_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm.client import submit_chat_task
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.models import ChatSubmitRequest, ChatSubmitResult
    from pallas.product.llm.turn_telemetry import telemetry_metadata

    submit_kernel = AsyncMock(return_value=ChatSubmitResult(task_id="task-1", status="processing", ok=True))
    monkeypatch.setattr("pallas.product.llm.kernel_runner.submit_kernel_llm_chat_task", submit_kernel)
    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: False)
    # submit gate 读全局配置，与用例 cfg 无关：放行以聚焦遥测元数据断言。
    from pallas.product.llm.submit_gate import LlmSubmitGateResult

    async def allow_gate() -> LlmSubmitGateResult:
        return LlmSubmitGateResult(allowed=True)

    monkeypatch.setattr("pallas.product.llm.client.assess_llm_submit_gate", allow_gate)
    monkeypatch.setattr(
        "pallas.product.llm.assembler.assemble_tool_bundle",
        lambda **_kwargs: {"tools_enabled": False, "tool_schemas": []},
    )
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_request_snapshot", lambda **_kwargs: "snapshot-1")

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="request-1",
            session_id="session-1",
            user_text="短句",
            system_prompt="system",
            task="llm_chat",
            llm_rewrite_metadata={
                "turn_id": "turn-1",
                "prompt": "secret",
                "reply_target": "fact",
            },
        ),
        # submit gate 现要求 provider 已配置；补最小 base_url + model 让用例
        # 聚焦遥测元数据断言（kernel 提交本身已被 mock）。
        cfg=LlmConfig(
            llm_chat_enabled=True,
            llm_governance_enabled=False,
            llm_base_url="http://127.0.0.1:9/v1",
            llm_model="test-model",
        ),
    )

    assert result.ok is True
    metadata = submit_kernel.await_args.kwargs["metadata"]
    assert metadata["reply_target"] == "fact"
    assert telemetry_metadata(metadata) == {"turn_id": "turn-1"}


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
