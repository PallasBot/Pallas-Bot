"""Focused retirement boundary tests: real registration/claim evidence + non-LLM positive controls.

Synthetic only: no real MaiBot/QQ/model/DB/HTTP.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from pallas.core.foundation.config import TaskManager


async def _noop_refresh() -> None:
    return None


def _seed_local(task_id: str, task_type: str) -> None:
    TaskManager._tasks[task_id] = {
        "bot_id": "111",
        "group_id": 222,
        "user_id": 333,
        "task_type": task_type,
        "start_time": 1.0,
    }
    TaskManager._terminal.pop(task_id, None)


def _clear_local(task_id: str) -> None:
    TaskManager._tasks.pop(task_id, None)
    TaskManager._terminal.pop(task_id, None)


# --------------------------------------------------------------- real claim evidence


async def test_historical_local_retired_task_claimed_once_then_404(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ai_callback import runner as runner_mod

    monkeypatch.setattr(TaskManager, "refresh", _noop_refresh)
    monkeypatch.setattr("pallas.core.platform.coord.redis_settings.coord_redis_task_required", lambda: False)
    monkeypatch.setattr("pallas.core.platform.shard.coord.ai_task_registry.remove_ai_task", lambda *_a: None)
    monkeypatch.setattr(
        runner_mod, "get_bot", lambda _id: (_ for _ in ()).throw(AssertionError("retired must not get_bot"))
    )

    task_id = "hist-local-retired"
    _seed_local(task_id, "llm_chat")
    try:
        first = await runner_mod.run_ai_callback(task_id, status="success", text="x")
        assert first == {"message": "ok", "status": "legacy_agent_retired"}
        # claim 已落终态：第二次领取 404，不再复活
        with pytest.raises(HTTPException) as excinfo:
            await runner_mod.run_ai_callback(task_id, status="success", text="x")
        assert excinfo.value.status_code == 404
    finally:
        _clear_local(task_id)


async def test_historical_redis_retired_task_claim_boundary_consumed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ai_callback import runner as runner_mod
    from pallas.core.platform.shard.coord import ai_task_registry

    monkeypatch.setattr(TaskManager, "refresh", _noop_refresh)
    monkeypatch.setattr("pallas.core.platform.coord.redis_settings.coord_redis_task_required", lambda: True)
    calls = {"n": 0}

    def claim(_task_id: str) -> dict | None:
        calls["n"] += 1
        if calls["n"] == 1:
            # 历史登记（未经 add_task 退役拦截）；claim 边界必须仍能读出，不被 normalize 丢弃
            return {"bot_id": "111", "group_id": 222, "task_type": "chat"}
        return None

    monkeypatch.setattr(ai_task_registry, "claim_ai_task_record", claim)
    monkeypatch.setattr(
        runner_mod, "get_bot", lambda _id: (_ for _ in ()).throw(AssertionError("retired must not get_bot"))
    )

    first = await runner_mod.run_ai_callback("hist-redis-retired", status="failed", text="x")
    assert first == {"message": "ok", "status": "legacy_agent_retired"}
    with pytest.raises(HTTPException) as excinfo:
        await runner_mod.run_ai_callback("hist-redis-retired", status="failed", text="x")
    assert excinfo.value.status_code == 404


# --------------------------------------------------------------- non-LLM positive controls

_NON_LLM_TASK_TYPES = ("draw", "sing", "play", "request", "tts")


@pytest.mark.parametrize("task_type", _NON_LLM_TASK_TYPES)
async def test_non_llm_media_task_registers_and_is_not_retired(monkeypatch: pytest.MonkeyPatch, task_type: str) -> None:
    from pallas.core.platform.ai_callback import runner as runner_mod

    monkeypatch.setattr(TaskManager, "refresh", _noop_refresh)
    monkeypatch.setattr("pallas.core.platform.coord.redis_settings.coord_redis_task_required", lambda: False)
    monkeypatch.setattr(
        "pallas.core.platform.shard.coord.ai_task_registry.register_ai_task", lambda *_a, **_k: "skipped"
    )
    monkeypatch.setattr("pallas.core.platform.shard.coord.ai_task_registry.remove_ai_task", lambda *_a: None)

    task_id = f"media-{task_type}"
    _clear_local(task_id)
    status = await TaskManager.add_task(
        task_id,
        {"bot_id": "1", "group_id": 2, "user_id": 3, "task_type": task_type, "start_time": 1.0},
    )
    assert status == "ok"  # 媒体任务类型不被退役拦截

    bot = MagicMock()
    bot.self_id = "1"
    bot.call_api = AsyncMock(return_value={"message_id": 1})
    monkeypatch.setattr(runner_mod, "get_bot", lambda _id: bot)
    _seed_local(task_id, task_type)
    try:
        result = await runner_mod.run_ai_callback(task_id, status="success", text="ok")
        assert "legacy_agent_retired" not in str(result)  # 走正常媒体回调路径
        assert TaskManager._tasks.get(task_id) is None  # 已领取
    finally:
        _clear_local(task_id)


# --------------------------------------------------------------- registration evidence


def test_retired_generation_modules_register_no_matchers(monkeypatch: pytest.MonkeyPatch) -> None:
    from nonebot import matcher as nb_matcher

    import packages.llm_chat  # noqa: F401

    def total() -> int:
        return sum(len(bucket) for bucket in nb_matcher.matchers.values())

    before = total()
    import packages.llm_chat.chat_message  # noqa: F401
    import packages.llm_chat.drunk_chat  # noqa: F401

    assert total() == before  # 显式重 import 不新增注册
    names = {
        getattr(getattr(matcher, "module", None), "__name__", "")
        for bucket in nb_matcher.matchers.values()
        for matcher in bucket
    }
    assert not any("chat_message" in name or "drunk_chat" in name for name in names)


def test_direct_runtime_registers_repeater_without_llm_chat() -> None:
    from pallas.core.platform.message_runtime import lifecycle

    lifecycle.reset_direct_runtime_for_tests()
    lifecycle.configure_direct_runtime()
    try:
        runtime = lifecycle.direct_runtime_for_group(0)
        assert runtime is not None
        ids = set(runtime._registry._handlers)
        assert "repeater.message" in ids
        assert "llm_chat.message" not in ids
    finally:
        lifecycle.reset_direct_runtime_for_tests()


def test_default_app_has_media_callback_but_no_llm_tools_http(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from pallas.core.platform.ai_callback import ai_bearer, http as http_mod
    from pallas.core.platform.bot_runtime import kernel_runtime

    app = FastAPI()
    monkeypatch.setattr(http_mod, "get_app", lambda: app)
    monkeypatch.setattr(http_mod, "_http_registered", False)
    monkeypatch.setattr(kernel_runtime, "_KERNEL_REGISTERED", False)
    monkeypatch.setattr(kernel_runtime, "is_hub_role", lambda: True)
    monkeypatch.setattr(ai_bearer, "resolve_ai_bearer_token", lambda: "test-token")
    monkeypatch.setattr(ai_bearer, "verify_ai_bearer", lambda value: value == "Bearer test-token")

    kernel_runtime.register_kernel_runtime()

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/callback/{task_id}" in paths
    assert "/pallas/api/internal/llm/tools/execute" not in paths
    with TestClient(app) as client:
        assert client.post("/callback/test", data={"status": "success"}).status_code == 401
        assert client.post(
            "/pallas/api/internal/llm/tools/execute", json={}, headers={"Authorization": "Bearer test-token"}
        ).status_code == 404
