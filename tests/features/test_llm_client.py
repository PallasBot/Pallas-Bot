from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.product.llm.client import delete_llm_chat_session, resolve_chat_messages, submit_chat_task
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.models import ChatSubmitRequest
from pallas.product.llm.task_routing import TaskRouteSpec


@pytest.fixture(autouse=True)
def stub_task_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.submit_gate import LlmSubmitGateResult

    async def allow_gate() -> LlmSubmitGateResult:
        return LlmSubmitGateResult(allowed=True)

    async def fake_resolve_chain(task: str, *, explicit_model: str | None = None) -> list[TaskRouteSpec]:
        task_name = str(task or "").strip().lower() or "llm_chat"
        return [
            TaskRouteSpec(
                task=task_name,
                resolved_model=str(explicit_model or "").strip() or None,
                provider_hint=None,
                source="explicit" if explicit_model else "config",
            )
        ]

    monkeypatch.setattr("pallas.product.llm.client.assess_llm_submit_gate", allow_gate)
    monkeypatch.setattr("pallas.product.llm.client.resolve_task_route_chain", fake_resolve_chain)


@pytest.mark.asyncio
async def test_submit_chat_task_legacy_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def json(self):
            return {"task_id": "task-1", "status": "processing"}

    async def fake_post(url: str, json: dict | None = None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("pallas.product.llm.client.HTTPXClient.post", fake_post)
    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: False)

    cfg = LlmConfig(
        ai_server_host="127.0.0.1",
        ai_server_port=9099,
        llm_chat_enabled=True,
        llm_governance_enabled=False,
        legacy_chat_endpoint="/api/llm/chat",
        legacy_chat_allowed=True,
        use_unified_chat_api=False,
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-1",
            session_id="sess-1",
            user_text="你好",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
        ),
        cfg=cfg,
    )
    assert result.ok is True
    assert result.task_id == "task-1"
    assert captured["url"] == "http://127.0.0.1:9099/api/llm/chat/req-1"
    assert captured["json"]["session"] == "sess-1"
    assert captured["json"]["system_prompt"] == "system"
    assert captured["json"]["text"].startswith("【用户消息")


@pytest.mark.asyncio
async def test_submit_chat_task_unified_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def json(self):
            return {"task_id": "task-u1", "status": "processing"}

    async def fake_post(url: str, json: dict | None = None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("pallas.product.llm.client.HTTPXClient.post", fake_post)
    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: False)

    cfg = LlmConfig(use_unified_chat_api=True, llm_chat_enabled=True, llm_governance_enabled=False)
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-u1",
            session_id="sess-u1",
            user_text="你好",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
            mode="drunk",
            token_count=50,
        ),
        cfg=cfg,
    )
    assert result.ok is True
    assert captured["url"] == "http://127.0.0.1:9099/api/v1/chat/completions/req-u1"
    payload = captured["json"]
    assert payload["capability"] == "llm.chat"
    assert payload["caller"]["plugin"] == "llm_chat"
    assert payload["payload"]["session_id"] == "sess-u1"
    assert payload["payload"]["system"] == "system"
    assert payload["payload"]["metadata"]["mode"] == "drunk"
    assert payload["payload"]["metadata"]["task"] == "drunk"
    assert payload["payload"]["metadata"]["task_route"]["task"] == "drunk"
    assert payload["payload"]["metadata"]["task_route"]["source"] == "config"
    assert payload["payload"]["metadata"]["token_count"] == 50
    assert payload["payload"]["messages"][-1]["content"].startswith("【用户消息")


@pytest.mark.asyncio
async def test_submit_chat_task_unified_llm_chat_payload_includes_agent_stage_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class FakeResponse:
        def json(self):
            return {"task_id": "task-u2", "status": "processing"}

    async def fake_post(url: str, json: dict | None = None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("pallas.product.llm.client.HTTPXClient.post", fake_post)
    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: False)
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.tool_metadata_for_chat",
        lambda **_kwargs: {
            "tools_enabled": True,
            "tool_schemas": [
                {"type": "function", "function": {"name": "arknights_operator_get"}},
                {"type": "function", "function": {"name": "command_roll"}},
            ],
        },
    )

    cfg = LlmConfig(use_unified_chat_api=True, llm_chat_enabled=True, llm_governance_enabled=False)
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-u2",
            session_id="sess-u2",
            user_text="帮我查一下能天使技能",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
            task="llm_chat",
            hybrid_retrieval_trace={"sources": ["memory"], "memory": {"hit_count": 1}},
            llm_rewrite_metadata={
                "variation_hint": "【本轮表达去重】\n- 最近解释偏满",
                "persona_affect_block": "【本轮牛格塑形】\n- 像顺口接话",
                "persona_shaping_active": True,
            },
        ),
        cfg=cfg,
    )
    assert result.ok is True
    metadata = captured["json"]["payload"]["metadata"]
    assert metadata["task"] == "llm_chat"
    assert metadata["task_route"]["task"] == "llm_chat"
    assert metadata["tools_enabled"] is True
    assert metadata["agent_stage_plan"] == ["plan", "tool_loop", "generate"]
    assert metadata["tool_schema_count"] == 2
    assert "最近解释偏满" in str(metadata.get("variation_hint") or "")
    assert "本轮牛格塑形" in str(metadata.get("persona_affect_block") or "")
    assert metadata.get("persona_shaping_active") is True
    assert metadata["hybrid_retrieval_trace"]["memory"]["hit_count"] == 1


@pytest.mark.asyncio
async def test_submit_chat_task_unified_pg_session_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def json(self):
            return {"task_id": "task-pg", "status": "processing"}

    async def fake_post(url: str, json: dict | None = None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    from pallas.product.llm.models import ChatCompletionMessage

    async def fake_build_messages(*args, **kwargs):
        return [
            ChatCompletionMessage(role="user", content="历史"),
            ChatCompletionMessage(role="assistant", content="嗯"),
            ChatCompletionMessage(role="user", content="【用户消息】你好"),
        ]

    monkeypatch.setattr("pallas.product.llm.client.HTTPXClient.post", fake_post)
    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: True)
    monkeypatch.setattr("pallas.product.llm.client.build_llm_chat_messages", fake_build_messages)

    cfg = LlmConfig(use_unified_chat_api=True, llm_chat_enabled=True, llm_governance_enabled=False)
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-pg",
            session_id="sess-stable",
            user_text="你好",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
        ),
        cfg=cfg,
    )
    assert result.ok is True
    payload = captured["json"]["payload"]
    assert payload["session_id"] == "req-pg"
    assert payload["metadata"]["pg_session"] is True
    assert len(payload["messages"]) == 3
    assert payload["messages"][-1]["role"] == "user"


@pytest.mark.asyncio
async def test_submit_chat_task_metadata_includes_runtime_state_summary_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def json(self):
            return {"task_id": "task-sum", "status": "processing"}

    async def fake_post(url: str, json: dict | None = None, **kwargs):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("pallas.product.llm.client.HTTPXClient.post", fake_post)
    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: False)

    cfg = LlmConfig(
        use_unified_chat_api=True,
        llm_chat_enabled=True,
        llm_session_enabled=True,
        llm_session_summary_enabled=True,
        llm_session_summary_threshold=24,
        llm_session_summary_keep_messages=6,
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-sum",
            session_id="sess-sum",
            user_text="你好",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
        ),
        cfg=cfg,
    )
    assert result.ok is True
    metadata = captured["json"]["payload"]["metadata"]
    assert metadata["runtime_state_summary_enabled"] is True
    assert metadata["session_summary"] == {
        "enabled": True,
        "threshold": 24,
        "keep_messages": 6,
    }


@pytest.mark.asyncio
async def test_submit_chat_task_metadata_disables_summary_when_session_off(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def json(self):
            return {"task_id": "task-sum-off", "status": "processing"}

    async def fake_post(url: str, json: dict | None = None, **kwargs):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("pallas.product.llm.client.HTTPXClient.post", fake_post)
    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: False)

    cfg = LlmConfig(
        use_unified_chat_api=True,
        llm_chat_enabled=True,
        llm_session_enabled=False,
        llm_session_summary_enabled=True,
    )
    await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-sum-off",
            session_id="sess-sum-off",
            user_text="你好",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
        ),
        cfg=cfg,
    )
    metadata = captured["json"]["payload"]["metadata"]
    assert metadata["runtime_state_summary_enabled"] is False
    assert "session_summary" not in metadata


@pytest.mark.asyncio
async def test_delete_llm_chat_session_unified(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200

    async def fake_delete(url: str, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr("pallas.product.llm.client.HTTPXClient.delete", fake_delete)

    ok = await delete_llm_chat_session("bot_group", cfg=LlmConfig(use_unified_chat_api=True))
    assert ok is True
    assert captured["url"] == "http://127.0.0.1:9099/api/v1/chat/completions/session/bot_group"


@pytest.mark.asyncio
async def test_submit_chat_task_rejects_when_llm_chat_disabled() -> None:
    cfg = LlmConfig(llm_chat_enabled=False)
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-off",
            session_id="sess-off",
            user_text="你好",
            system_prompt="system",
        ),
        cfg=cfg,
    )
    assert result.ok is False
    assert result.status == "llm_chat_disabled"


@pytest.mark.asyncio
async def test_resolve_chat_messages_repeater_skips_pg_history(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_build(*_args, **_kwargs):
        raise AssertionError("repeater should not load pg session history")

    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: True)
    monkeypatch.setattr("pallas.product.llm.client.build_llm_chat_messages", fail_build)

    messages = await resolve_chat_messages(
        ChatSubmitRequest(
            request_id="req-rp",
            session_id="repeater_fb_1_2_3",
            user_text="你好",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
            task="repeater_fallback",
        ),
        cfg=LlmConfig(llm_chat_enabled=True),
    )
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert "你好" in messages[0].content


@pytest.mark.asyncio
async def test_submit_chat_task_repeater_payload_has_single_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def json(self):
            return {"task_id": "task-rp", "status": "processing"}

    async def fake_post(url: str, json: dict | None = None, **kwargs):
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("pallas.product.llm.client.HTTPXClient.post", fake_post)
    monkeypatch.setattr("pallas.product.llm.client.is_llm_session_store_available", lambda: True)
    monkeypatch.setattr("pallas.product.llm.client.check_repeater_llm_allowed", AsyncMock(return_value=None))
    slot = MagicMock(acquired=True)
    monkeypatch.setattr("pallas.product.llm.client.try_acquire_repeater_llm_slot", AsyncMock(return_value=slot))

    async def fake_route_chain(task: str, *, explicit_model: str | None = None) -> list[TaskRouteSpec]:
        _ = explicit_model
        return [
            TaskRouteSpec(
                task=task,
                resolved_model="qwen3:14b",
                provider_hint="local",
                source="ai_health",
            )
        ]

    monkeypatch.setattr("pallas.product.llm.client.resolve_task_route_chain", fake_route_chain)

    cfg = LlmConfig(use_unified_chat_api=True, llm_chat_enabled=True, llm_governance_enabled=False)
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-rp2",
            session_id="repeater_pl_1_2_3",
            user_text="【候选回复】原句",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
            task="repeater_polish",
        ),
        cfg=cfg,
    )
    assert result.ok is True
    assert len(captured["json"]["payload"]["messages"]) == 1
    assert captured["json"]["payload"]["metadata"]["resolved_model"] == "qwen3:14b"
    assert captured["json"]["payload"]["metadata"]["task_route"]["task"] == "repeater_polish"


@pytest.mark.asyncio
async def test_submit_chat_task_rejects_empty_user_text() -> None:
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-2",
            session_id="sess-2",
            user_text="   ",
            system_prompt="system",
        ),
        cfg=LlmConfig(llm_chat_enabled=True),
    )
    assert result.ok is False
    assert result.status == "empty_user_message"


def test_resolve_llm_chat_enabled_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.availability import is_drunk_chat_enabled
    from pallas.product.llm.config import (
        clear_llm_config_cache,
        resolve_legacy_rwkv_drunk_chat_enabled,
        resolve_llm_chat_enabled,
    )

    def set_env(values: dict[str, str | None]) -> None:
        def fake_raw(key: str) -> str | None:
            return values.get(key)

        monkeypatch.setattr("pallas.product.llm.config.repo_env_raw_value", fake_raw)
        chat_pkg = types.ModuleType("packages.chat")
        chat_cfg = types.ModuleType("packages.chat.config")
        chat_cfg.get_chat_config = lambda: type("Cfg", (), {"chat_enable": False})()
        monkeypatch.setitem(sys.modules, "packages.chat", chat_pkg)
        monkeypatch.setitem(sys.modules, "packages.chat.config", chat_cfg)
        monkeypatch.setattr(
            chat_pkg,
            "config",
            chat_cfg,
            raising=False,
        )
        clear_llm_config_cache()

    set_env({"LLM_CHAT_ENABLED": "false", "CHAT_ENABLE": "true"})
    assert resolve_llm_chat_enabled() is False
    assert resolve_legacy_rwkv_drunk_chat_enabled() is False
    assert is_drunk_chat_enabled() is False

    set_env({"CHAT_ENABLE": "true"})
    assert resolve_llm_chat_enabled() is False
    assert resolve_legacy_rwkv_drunk_chat_enabled() is True
    assert is_drunk_chat_enabled() is True

    set_env({"LLM_CHAT_ENABLE": "false", "CHAT_ENABLE": "true"})
    assert resolve_llm_chat_enabled() is False
    assert resolve_legacy_rwkv_drunk_chat_enabled() is True

    set_env({"LLM_CHAT_ENABLED": "true", "CHAT_ENABLE": "false"})
    assert resolve_llm_chat_enabled() is True
    assert resolve_legacy_rwkv_drunk_chat_enabled() is False

    set_env({})
    assert resolve_llm_chat_enabled() is False
    assert resolve_legacy_rwkv_drunk_chat_enabled() is False
