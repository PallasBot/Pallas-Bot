"""Focused tests for the self-developed agent retirement (global).

Synthetic probes only: no real MaiBot/QQ/model/DB/HTTP.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from pallas.core.platform.ai_callback.task_types import (
    RETIRED_CHAT_TASK_TYPES,
    is_retired_chat_task_type,
    normalize_task_type,
)

# --------------------------------------------------------------- task types


def test_retired_chat_task_types_exact_and_normalized():
    assert RETIRED_CHAT_TASK_TYPES == frozenset({"llm_chat", "ollama", "chat"})
    for value in ("llm_chat", "LLM_CHAT", " ollama ", "Chat"):
        assert is_retired_chat_task_type(value) is True
    for value in ("draw", "sing", "tts", "", None):
        assert is_retired_chat_task_type(value) is False
    assert normalize_task_type(" Chat ") == "chat"


# --------------------------------------------------------------- submit entry


async def test_submit_chat_task_returns_retired_before_any_side_effect(monkeypatch):
    from pallas.product.llm import client as client_mod
    from pallas.product.llm.models import ChatSubmitRequest

    def _boom(*_args, **_kwargs):
        raise AssertionError("side effect before retirement gate")

    for name in (
        "get_llm_config",
        "resolve_chat_messages",
        "is_llm_session_store_available",
        "assess_legacy_chat_submit",
        "resolve_task_route_chain",
    ):
        if hasattr(client_mod, name):
            monkeypatch.setattr(client_mod, name, _boom)
    monkeypatch.setattr("pallas.product.llm.availability.llm_plugin_disabled_for_scope", _boom)

    request = ChatSubmitRequest(
        request_id="r1",
        session_id="s1",
        user_text="hi",
        system_prompt="p",
        bot_id=1,
        group_id=2,
        user_id=3,
    )
    result = await client_mod.submit_chat_task(request)
    assert result.ok is False
    assert result.status == "legacy_agent_retired"


async def test_kernel_submit_returns_retired(monkeypatch):
    from pallas.product.llm import kernel_runner as kr
    from pallas.product.llm.models import ChatSubmitRequest

    called: list[str] = []
    monkeypatch.setattr(kr, "try_acquire_llm_execution_slot", lambda *a, **k: called.append("slot"), raising=False)

    request = ChatSubmitRequest(request_id="r2", session_id="s2", user_text="hi", system_prompt="p")
    result = await kr.submit_kernel_llm_chat_task(
        request,
        system_prompt="p",
        messages=[],
        metadata={},
        timer=SimpleNamespace(mark=lambda *a, **k: None, finish=lambda *a, **k: None),
        message_count=0,
        cfg=SimpleNamespace(),
    )
    assert result.status == "legacy_agent_retired"
    assert called == []


async def test_run_kernel_chat_job_exits_retired_and_releases_slot(monkeypatch):
    from pallas.product.llm import kernel_runner as kr

    released: list[object] = []
    monkeypatch.setattr(kr, "release_llm_execution_slot", lambda slot, cfg=None: released.append(slot))

    await kr.run_kernel_chat_job(
        "r3",
        system_prompt="p",
        messages=[],
        metadata={"bot_id": 1, "group_id": 2},
        cfg=SimpleNamespace(),
        execution_slot="slot-1",
    )
    assert released == ["slot-1"]


# --------------------------------------------------------------- rwkv / sessions


async def test_rwkv_submit_and_delete_do_not_use_http(monkeypatch):
    from pallas.product.llm import legacy_rwkv as rwkv

    def _boom(*_args, **_kwargs):
        raise AssertionError("HTTP must not be used")

    monkeypatch.setattr(rwkv, "HTTPXClient", _boom, raising=False)
    assert await rwkv.submit_rwkv_drunk_chat(request_id="r", session="s", text="t") == ("", False)
    assert await rwkv.delete_rwkv_chat_session("s") is False


async def test_delete_llm_chat_session_does_not_use_http(monkeypatch):
    from pallas.product.llm import client as client_mod

    def _boom(*_args, **_kwargs):
        raise AssertionError("HTTP must not be used")

    monkeypatch.setattr(client_mod, "HTTPXClient", _boom, raising=False)
    assert await client_mod.delete_llm_chat_session("session") is False


# --------------------------------------------------------------- task registration


async def test_task_manager_add_task_rejects_retired_without_write(monkeypatch):
    from pallas.core.foundation.config import TaskManager

    async def _noop_refresh():
        return None

    monkeypatch.setattr(TaskManager, "refresh", _noop_refresh)
    TaskManager._tasks.clear()
    status = await TaskManager.add_task(
        "retired-1",
        {"bot_id": "1", "group_id": 2, "user_id": 3, "task_type": "LLM_CHAT", "start_time": 1.0},
    )
    assert status == "invalid"
    assert "retired-1" not in TaskManager._tasks


def test_redis_register_rejects_retired_without_write(monkeypatch):
    from pallas.core.platform.shard.coord import ai_task_registry as registry

    written: list[object] = []
    monkeypatch.setattr(registry, "write_ai_task_redis_sync", lambda *a, **k: written.append(a) or "ok")
    status = registry.register_ai_task("t1", {"bot_id": "1", "task_type": " ollama ", "start_time": 1.0})
    assert status == "conflict"
    assert written == []


async def test_register_ai_task_from_aux_410_after_token(monkeypatch):
    from fastapi import HTTPException

    from pallas.core.platform.ai_callback import task_registration as tr

    added: list[object] = []

    async def _add(*args, **kwargs):
        added.append(args)
        return "ok"

    monkeypatch.setattr(tr.TaskManager, "add_task", _add)
    monkeypatch.setattr(tr, "verify_internal_token", lambda purpose, token: True)

    with pytest.raises(HTTPException) as excinfo:
        await tr.register_ai_task_from_aux("t1", {"bot_id": "1", "task_type": "chat", "start_time": 1.0})
    assert excinfo.value.status_code == 410
    assert excinfo.value.detail == "legacy_agent_retired"
    assert added == []

    # token still comes first: an invalid token is 403, never 410
    monkeypatch.setattr(tr, "verify_internal_token", lambda purpose, token: False)
    with pytest.raises(HTTPException) as excinfo2:
        await tr.register_ai_task_from_aux("t1", {"bot_id": "1", "task_type": "chat", "start_time": 1.0})
    assert excinfo2.value.status_code == 403


# --------------------------------------------------------------- callback runner


async def test_run_ai_callback_retired_consumes_without_side_effects(monkeypatch):
    from pallas.core.platform.ai_callback import runner as runner_mod

    sent: list[object] = []
    traced: list[object] = []

    async def _claim(_task_id):
        return {"bot_id": "111", "group_id": 222, "user_id": 333, "task_type": "llm_chat"}

    monkeypatch.setattr(runner_mod, "resolve_callback_task", _claim)
    monkeypatch.setattr(runner_mod, "get_bot", lambda _id: sent.append("get_bot"))
    monkeypatch.setattr("pallas.product.llm.runtime_debug.append_runtime_trace", lambda **k: traced.append(k))

    result = await runner_mod.run_ai_callback("t", status="success", text="x")
    assert result == {"message": "ok", "status": "legacy_agent_retired"}
    assert sent == []
    assert traced == []


# --------------------------------------------------------------- registration removals


def test_llm_only_generation_registrations_are_gone():
    import packages.llm_chat.chat_message as chat_message
    import packages.llm_chat.drunk_chat as drunk_chat

    # LLM 专属生成入口已退役
    assert not hasattr(chat_message, "llm_chat_msg")
    assert not hasattr(drunk_chat, "drunk_msg")


def test_non_llm_repeater_entries_are_preserved():
    import packages.repeater.emoji_reaction as emoji_reaction
    import packages.repeater.handlers.message as repeater_message
    import packages.repeater.handlers.scheduler as scheduler

    # 非 LLM 自动能力（复读接话/主动发言/自动表情）保留
    assert hasattr(repeater_message, "prepare_repeater_reply")
    assert hasattr(repeater_message, "capture_repeater_only")
    assert hasattr(scheduler, "speak_up")
    assert hasattr(emoji_reaction, "reaction_msg")
    assert hasattr(emoji_reaction, "reaction_msg_with_face")
    assert hasattr(emoji_reaction, "auto_reaction_add")


def test_kernel_runtime_does_not_register_llm_tools_http():
    from pallas.core.platform.bot_runtime import kernel_runtime

    assert not hasattr(kernel_runtime, "register_llm_tools_http")


def test_llm_chat_package_does_not_import_old_generation_modules():
    # cold import check: importing the plugin package must not pull the retired
    # generation modules (which would re-register their matchers).
    import packages.llm_chat  # noqa: F401

    assert "packages.llm_chat.chat_message" not in sys.modules or not hasattr(
        sys.modules["packages.llm_chat.chat_message"], "llm_chat_msg"
    )


def test_schedule_kernel_chat_job_does_not_create_task_and_releases_slot(monkeypatch) -> None:
    from pallas.product.llm import kernel_runner as kr

    created: list[object] = []
    released: list[object] = []
    monkeypatch.setattr(kr.asyncio, "create_task", lambda *a, **k: created.append(a) or object())
    monkeypatch.setattr(kr, "release_llm_execution_slot", lambda slot, cfg=None: released.append(slot))

    kr.schedule_kernel_chat_job(
        "r",
        system_prompt="p",
        messages=[],
        metadata={},
        cfg=SimpleNamespace(),
        execution_slot="slot-1",
    )

    assert created == []
    assert released == ["slot-1"]


async def test_legacy_submit_impl_cannot_trigger_old_generation(monkeypatch) -> None:
    from pallas.product.llm import kernel_runner as kr
    from pallas.product.llm.client import _submit_chat_task_impl
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.models import ChatSubmitRequest

    scheduled: list[object] = []
    monkeypatch.setattr(kr, "schedule_kernel_chat_job", lambda *a, **k: scheduled.append(a))
    monkeypatch.setattr(kr, "try_acquire_llm_execution_slot", lambda *a, **k: "slot", raising=False)

    result = await _submit_chat_task_impl(
        ChatSubmitRequest(request_id="r", session_id="s", user_text="hi", system_prompt="p"),
        cfg=LlmConfig(llm_chat_enabled=True, llm_base_url="http://127.0.0.1:9/v1", llm_model="m"),
    )

    assert result.ok is False  # 历史 impl 也不可能产出可运行任务
    assert result.status != "processing"
    assert scheduled == []
