"""runtime_debug 落盘失败时内核正常产出不受影响的入口级隔离。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.config import LlmConfig


def _allow_live_llm_gate(monkeypatch: pytest.MonkeyPatch, cfg: LlmConfig) -> None:
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)
    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", AsyncMock(return_value=False))


@pytest.mark.asyncio
async def test_kernel_success_delivers_when_runtime_debug_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import kernel_runner

    cfg = LlmConfig(
        llm_base_url="http://example.test/v1",
        llm_model="demo",
        llm_chat_enabled=True,
        use_unified_chat_api=True,
        llm_governance_enabled=False,
        llm_tools_enabled=False,
        llm_persona_output_firewall={"enabled": False},
    )
    _allow_live_llm_gate(monkeypatch, cfg)

    delivered: list[tuple[str, str, str]] = []

    async def fake_complete(**_kwargs):
        return "内核回复", {"role": "assistant", "content": "内核回复"}

    async def fake_deliver(task_id, *, status, text=None, **_kwargs):
        delivered.append((task_id, status, text or ""))
        return {"message": "ok"}

    def broken_runtime_debug_dir():
        raise OSError("runtime debug dir unavailable")

    monkeypatch.setattr(kernel_runner, "complete_with_tool_loop", fake_complete)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", fake_deliver)
    monkeypatch.setattr(kernel_runner.TaskManager, "remove_task", AsyncMock())
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.runtime_debug_dir",
        broken_runtime_debug_dir,
    )

    await kernel_runner.run_kernel_chat_job(
        "trace-fail-task",
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        metadata={"bot_id": 1, "group_id": 2},
        cfg=cfg,
    )

    assert delivered == [("trace-fail-task", "success", "内核回复")]


@pytest.fixture(autouse=True)
def _historical_legacy_agent_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """历史内核/输出测试：自研 agent 生成已全局退役；还原旧聊天 exit gate 以隔离纯算法断言。"""
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
