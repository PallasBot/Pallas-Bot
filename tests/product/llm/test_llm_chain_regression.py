from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import (
    LlmToolSource,
    LlmToolSpec,
    clear_tool_registry,
    register_tool,
)


@pytest.fixture(autouse=True)
def reset_tools() -> None:
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()
    yield
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()


@pytest.fixture
def stub_task_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.shard.coord import ai_task_registry

    monkeypatch.setattr(ai_task_registry, "register_ai_task", lambda *_args: None)
    monkeypatch.setattr(ai_task_registry, "remove_ai_task", lambda *_args: None)


@pytest.mark.asyncio
async def test_required_tool_failure_reaches_delivery_with_matching_trace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    stub_task_registry: None,
) -> None:
    from pallas.core.foundation.config import TaskManager
    from pallas.core.platform.ai_callback import runner as callback_runner
    from pallas.core.platform.ai_callback.delivery import DeliveryReceipt
    from pallas.product.llm import delivery as llm_delivery
    from pallas.product.llm import kernel_runner
    from pallas.product.llm.tools import registry

    executions = 0
    provider_calls = 0
    traces: list[dict] = []
    events: list[dict] = []
    messages: list[str] = []
    history: list[tuple] = []
    request_id = "required-tool-failure"
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    async def failing_lookup(_args, _context=None):
        nonlocal executions
        executions += 1
        raise RuntimeError("lookup unavailable")

    register_tool(
        LlmToolSpec(
            name="social.lookup",
            description="读取群内资料",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"social"}),
            handler=failing_lookup,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}),
        )
    )
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)

    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_tools_enabled=True,
        llm_persona_output_firewall={"enabled": False},
        llm_reply_postprocess_enabled=False,
    )

    def active_config():
        return cfg

    async def scope_enabled(_bot_id, _group_id):
        return False

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", active_config)
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", active_config)
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)
    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", scope_enabled)

    async def fake_provider(_messages, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "lookup-1",
                    "type": "function",
                    "function": {"name": "social__lookup", "arguments": "{}"},
                }
            ],
        }

    async def sender(_bot, _group_id, text, **_kwargs):
        messages.append(text)
        return DeliveryReceipt(delivered=True, message_id=400 + len(messages))

    async def append_history(*fields):
        history.append(fields)

    from pallas.core.platform.shard.coord import ai_task_registry

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_provider)
    monkeypatch.setattr(callback_runner, "get_bot", lambda _bot_id: SimpleNamespace(self_id="1"))
    monkeypatch.setattr("pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt", sender)
    monkeypatch.setattr(llm_delivery, "get_llm_config", active_config)
    monkeypatch.setattr(llm_delivery, "append_llm_message", append_history)
    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.schedule_auto_save_group_episode", lambda **_kwargs: None
    )
    monkeypatch.setattr(llm_delivery, "record_turn_event", lambda **fields: events.append(fields))
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace",
        lambda **kwargs: traces.append(kwargs["trace"]),
    )
    monkeypatch.setattr(ai_task_registry, "register_ai_task", lambda *_args: None)
    monkeypatch.setattr(ai_task_registry, "remove_ai_task", lambda *_args: None)

    await TaskManager.add_task(
        request_id,
        {
            "task_type": "llm_chat",
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "user_text": "查一下",
            "turn_id": "turn-tool-failure",
            "start_time": time.time(),
        },
    )

    await kernel_runner.run_kernel_chat_job(
        request_id,
        system_prompt="sys",
        messages=[{"role": "user", "content": "查一下"}],
        metadata={
            "task": "llm_chat",
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "tools_enabled": True,
            "tool_choice_prefer": "required",
            "tool_schemas": [{"type": "function", "function": {"name": "social__lookup"}}],
        },
        cfg=cfg,
    )

    assert executions == 1
    assert provider_calls == 1
    agent_trace = next(trace for trace in traces if trace.get("status") == "required_tool_failed")
    assert agent_trace["status"] == "required_tool_failed"
    assert agent_trace["successful_query_call_count"] == 0
    assert agent_trace["successful_side_effect_call_count"] == 0
    assert agent_trace["failed_tool_call_count"] == 1
    assert agent_trace["rounds"][0]["calls"][0]["ok"] is False
    delivery_event = next(event for event in events if event["stage"] == "delivery")
    assert delivery_event["delivery_status"] == "sent"
    assert delivery_event["sent_bubble_count"] == delivery_event["total_bubble_count"] == 1
    assert history[-1][3] == "assistant"
    assert messages[0].rstrip("。") == history[-1][4].rstrip("。")
    assert await TaskManager.get_task(request_id) is None


@pytest.mark.asyncio
async def test_switch_closed_on_provider_tool_response_prevents_tool_and_delivery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    stub_task_registry: None,
) -> None:
    from pallas.core.foundation.config import TaskManager
    from pallas.core.platform.shard.coord import ai_task_registry
    from pallas.product.llm import kernel_runner
    from pallas.product.llm.tools import registry

    cfg = LlmConfig(llm_chat_enabled=True, llm_tools_enabled=True)
    live_cfg = {"value": cfg}
    side_effects = 0
    provider_calls = 0
    delivered = AsyncMock()
    traces: list[dict] = []
    events: list[dict] = []
    request_id = "switch-before-tool-effect"
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    async def side_effect_handler(_args, _context=None):
        nonlocal side_effects
        side_effects += 1
        return {"ok": True, "result": {"summary": "done"}}

    register_tool(
        LlmToolSpec(
            name="demo.write",
            description="写入测试副作用",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=side_effect_handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
        )
    )
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)

    async def scope_enabled(_bot_id, _group_id):
        return False

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: live_cfg["value"])
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", lambda: live_cfg["value"])
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)
    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", scope_enabled)

    async def fake_provider(_messages, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        live_cfg["value"] = LlmConfig(llm_chat_enabled=False, llm_tools_enabled=True)
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "write-1",
                    "type": "function",
                    "function": {"name": "demo__write", "arguments": "{}"},
                }
            ],
        }

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", fake_provider)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", delivered)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace", lambda **kwargs: traces.append(kwargs["trace"])
    )
    monkeypatch.setattr("pallas.product.llm.turn_telemetry.record_turn_event", lambda **fields: events.append(fields))
    monkeypatch.setattr(ai_task_registry, "register_ai_task", lambda *_args: None)
    monkeypatch.setattr(ai_task_registry, "remove_ai_task", lambda *_args: None)

    await TaskManager.add_task(
        request_id,
        {
            "task_type": "llm_chat",
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "turn_id": "turn-switch-before-tool",
            "start_time": time.time(),
        },
    )
    await kernel_runner.run_kernel_chat_job(
        request_id,
        system_prompt="sys",
        messages=[{"role": "user", "content": "执行"}],
        metadata={
            "task": "llm_chat",
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "demo__write"}}],
            "turn_id": "turn-switch-before-tool",
        },
        cfg=cfg,
    )

    assert provider_calls == 1
    assert side_effects == 0
    delivered.assert_not_awaited()
    assert traces[-1]["skip_reason"] == "global_disabled_after_submit"
    assert events[-1]["turn_id"] == "turn-switch-before-tool"
    assert events[-1]["decision"] == "skipped"
    assert await TaskManager.get_task(request_id) is None


@pytest.mark.asyncio
async def test_captured_disabled_switch_skips_provider_tools_and_delivery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    stub_task_registry: None,
) -> None:
    from pallas.core.foundation.config import TaskManager
    from pallas.core.platform.shard.coord import ai_task_registry
    from pallas.product.llm import kernel_runner

    cfg = LlmConfig(llm_chat_enabled=False, llm_tools_enabled=True)
    provider = AsyncMock()
    tool = AsyncMock(return_value={"ok": True})
    delivered = AsyncMock()
    traces: list[dict] = []
    request_id = "captured-disabled-kernel"
    register_tool(
        LlmToolSpec(
            name="demo.write",
            description="写入测试副作用",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=tool,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
        )
    )
    from pallas.product.llm.tools import registry

    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: LlmConfig(llm_chat_enabled=True))
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", lambda: LlmConfig(llm_chat_enabled=True))
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)
    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", AsyncMock(return_value=False))
    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", provider)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", delivered)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace", lambda **kwargs: traces.append(kwargs["trace"])
    )
    monkeypatch.setattr(ai_task_registry, "register_ai_task", lambda *_args: None)
    monkeypatch.setattr(ai_task_registry, "remove_ai_task", lambda *_args: None)

    await TaskManager.add_task(
        request_id,
        {"task_type": "llm_chat", "bot_id": 1, "group_id": 2, "user_id": 3, "start_time": time.time()},
    )
    await kernel_runner.run_kernel_chat_job(
        request_id,
        system_prompt="sys",
        messages=[{"role": "user", "content": "执行"}],
        metadata={
            "task": "llm_chat",
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "demo__write"}}],
        },
        cfg=cfg,
    )

    provider.assert_not_awaited()
    tool.assert_not_awaited()
    delivered.assert_not_awaited()
    assert traces[-1]["skip_reason"] == "global_disabled_after_submit"
    assert await TaskManager.get_task(request_id) is None


@pytest.mark.asyncio
async def test_switch_closed_during_tool_effect_is_traced_without_claiming_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    stub_task_registry: None,
) -> None:
    from pallas.core.foundation.config import TaskManager
    from pallas.core.platform.shard.coord import ai_task_registry
    from pallas.product.llm import kernel_runner
    from pallas.product.llm.tools import registry

    cfg = LlmConfig(llm_chat_enabled=True, llm_tools_enabled=True)
    live_cfg = {"value": cfg}
    tool_calls = 0
    provider_calls = 0
    delivered = AsyncMock()
    traces: list[dict] = []
    request_id = "switch-during-tool-effect"
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    async def effect(_args, _context=None):
        nonlocal tool_calls
        tool_calls += 1
        live_cfg["value"] = LlmConfig(llm_chat_enabled=False, llm_tools_enabled=True)
        return {"ok": True, "result": {"summary": "already applied"}}

    register_tool(
        LlmToolSpec(
            name="demo.apply",
            description="测试外部副作用",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"demo"}),
            handler=effect,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
        )
    )
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: live_cfg["value"])
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", lambda: live_cfg["value"])
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)
    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", AsyncMock(return_value=False))
    monkeypatch.setattr(ai_task_registry, "register_ai_task", lambda *_args: None)
    monkeypatch.setattr(ai_task_registry, "remove_ai_task", lambda *_args: None)
    monkeypatch.setattr(kernel_runner, "deliver_llm_chat_result", delivered)
    monkeypatch.setattr(
        "pallas.product.llm.runtime_debug.append_runtime_trace", lambda **kwargs: traces.append(kwargs["trace"])
    )

    async def provider(_messages, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "apply-1",
                    "type": "function",
                    "function": {"name": "demo__apply", "arguments": "{}"},
                }
            ],
        }

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", provider)
    await TaskManager.add_task(
        request_id,
        {"task_type": "llm_chat", "bot_id": 1, "group_id": 2, "user_id": 3, "start_time": time.time()},
    )

    await kernel_runner.run_kernel_chat_job(
        request_id,
        system_prompt="sys",
        messages=[{"role": "user", "content": "执行"}],
        metadata={
            "task": "llm_chat",
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "tools_enabled": True,
            "tool_schemas": [{"type": "function", "function": {"name": "demo__apply"}}],
        },
        cfg=cfg,
    )

    assert tool_calls == provider_calls == 1
    delivered.assert_not_awaited()
    assert traces[-1]["skip_reason"] == "global_disabled_after_submit"
    assert traces[-1]["side_effect_started"] is True
    assert await TaskManager.get_task(request_id) is None


@pytest.mark.asyncio
async def test_partial_delivery_through_kernel_callback_preserves_sent_bubble_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    stub_task_registry: None,
) -> None:
    from pallas.core.foundation.config import TaskManager
    from pallas.core.platform.ai_callback import runner as callback_runner
    from pallas.core.platform.ai_callback.delivery import DeliveryReceipt
    from pallas.core.platform.shard.coord import ai_task_registry
    from pallas.product.llm import delivery as llm_delivery
    from pallas.product.llm import kernel_runner
    from pallas.product.llm.bot_reply_context import clear_bot_reply_context_for_tests, lookup_bot_reply_context

    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_persona_output_firewall={"enabled": False},
        llm_reply_postprocess_enabled=False,
    )
    request_id = "partial-kernel-callback"
    messages: list[str] = []
    history = AsyncMock(return_value=True)
    events: list[dict] = []
    clear_bot_reply_context_for_tests()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    async def scope_enabled(_bot_id, _group_id):
        return False

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.availability.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)
    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", scope_enabled)
    monkeypatch.setattr(llm_delivery, "get_llm_config", lambda: cfg)
    monkeypatch.setattr(llm_delivery, "append_llm_message", history)
    monkeypatch.setattr(llm_delivery, "record_turn_event", lambda **fields: events.append(fields))
    monkeypatch.setattr(llm_delivery, "sleep_between_bubbles", AsyncMock())
    monkeypatch.setattr(
        "pallas.product.llm.memory.auto_episode.schedule_auto_save_group_episode", lambda **_kwargs: None
    )
    monkeypatch.setattr(callback_runner, "get_bot", lambda _bot_id: SimpleNamespace(self_id="1"))

    async def sender(_bot, _group_id, text, **_kwargs):
        messages.append(text)
        return DeliveryReceipt(delivered=len(messages) == 1, message_id=501 if len(messages) == 1 else None)

    monkeypatch.setattr("pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt", sender)
    monkeypatch.setattr(ai_task_registry, "register_ai_task", lambda *_args: None)
    monkeypatch.setattr(ai_task_registry, "remove_ai_task", lambda *_args: None)
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_runtime_trace", lambda **_kwargs: None)

    async def provider(_messages, **_kwargs):
        return {
            "role": "assistant",
            "content": '{"reply_segments":["第一泡","第二泡","第三泡"]}',
        }

    monkeypatch.setattr("pallas.product.llm.tool_loop.complete_chat_message", provider)
    await TaskManager.add_task(
        request_id,
        {
            "task_type": "llm_chat",
            "bot_id": 1,
            "group_id": 2,
            "user_id": 3,
            "user_text": "继续",
            "turn_id": "turn-partial-callback",
            "start_time": time.time(),
        },
    )

    await kernel_runner.run_kernel_chat_job(
        request_id,
        system_prompt="sys",
        messages=[{"role": "user", "content": "继续"}],
        metadata={"task": "llm_chat", "bot_id": 1, "group_id": 2, "user_id": 3},
        cfg=cfg,
    )

    assert messages == ["第一泡", "第二泡"]
    assert lookup_bot_reply_context(group_id=2, bot_id=1, message_id=501) == "第一泡"
    assert history.assert_not_awaited() is None
    delivery_event = next(event for event in events if event["stage"] == "delivery")
    assert delivery_event["delivery_status"] == "partial"
    assert delivery_event["sent_bubble_count"] == 1
    assert delivery_event["total_bubble_count"] == 3
    assert await TaskManager.get_task(request_id) is None
