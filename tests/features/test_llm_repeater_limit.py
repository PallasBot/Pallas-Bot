from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.repeater_limit import (
    clear_repeater_llm_limit_state,
    is_repeater_llm_task,
    per_worker_global_rpm_limit,
    try_consume_local_rpm,
)
from pallas.product.llm.task_routing import TaskRouteSpec


@pytest.fixture(autouse=True)
def stub_task_route(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(task: str, *, explicit_model: str | None = None) -> TaskRouteSpec:
        task_name = str(task or "").strip().lower() or "llm_chat"
        return TaskRouteSpec(
            task=task_name,
            resolved_model=str(explicit_model or "").strip() or None,
            provider_hint=None,
            source="explicit" if explicit_model else "config",
        )

    monkeypatch.setattr("pallas.product.llm.client.resolve_task_route", fake_resolve)


def test_is_repeater_llm_task() -> None:
    assert is_repeater_llm_task("repeater_fallback") is True
    assert is_repeater_llm_task("repeater_polish") is True
    assert is_repeater_llm_task("llm_chat") is False


def test_per_worker_global_rpm_limit_scales_by_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pallas.product.llm.repeater_limit.estimated_production_workers", lambda: 8)
    cfg = LlmConfig(llm_repeater_global_rpm=10)
    assert per_worker_global_rpm_limit(cfg) == 2


def test_try_consume_local_rpm_respects_per_worker_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_repeater_llm_limit_state()
    monkeypatch.setattr("pallas.product.llm.repeater_limit.estimated_production_workers", lambda: 1)
    cfg = LlmConfig(llm_repeater_global_rpm=2)
    assert try_consume_local_rpm(cfg) is True
    assert try_consume_local_rpm(cfg) is True
    assert try_consume_local_rpm(cfg) is False


@pytest.mark.asyncio
async def test_check_repeater_llm_allowed_group_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.repeater_limit import check_repeater_llm_allowed, refresh_repeater_group_cooldown

    clear_repeater_llm_limit_state()
    cfg = LlmConfig(
        llm_governance_enabled=True,
        llm_repeater_group_cooldown_sec=60,
        llm_repeater_global_rpm=600,
    )
    monkeypatch.setattr("pallas.product.llm.repeater_limit.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.repeater_limit.try_consume_global_rpm", lambda _cfg=None: True)

    assert await check_repeater_llm_allowed(100, 200, cfg=cfg) is None
    await refresh_repeater_group_cooldown(100, 200)
    assert await check_repeater_llm_allowed(100, 200, cfg=cfg) == "repeater_group_cooldown"


@pytest.mark.asyncio
async def test_submit_chat_task_repeater_uses_repeater_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.client import submit_chat_task
    from pallas.product.llm.models import ChatSubmitRequest

    cfg = LlmConfig(llm_chat_enabled=True, llm_governance_enabled=True, use_unified_chat_api=True)

    async def fake_check(*args, **kwargs):
        return "repeater_global_rpm"

    monkeypatch.setattr("pallas.product.llm.client.check_repeater_llm_allowed", fake_check)

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-1",
            session_id="sess-1",
            user_text="你好",
            system_prompt="system",
            bot_id=1,
            group_id=2,
            user_id=3,
            task="repeater_fallback",
        ),
        cfg=cfg,
    )
    assert result.ok is False
    assert result.status == "repeater_global_rpm"


@pytest.mark.asyncio
async def test_submit_chat_task_llm_chat_still_uses_chat_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.client import submit_chat_task
    from pallas.product.llm.models import ChatSubmitRequest

    cfg = LlmConfig(llm_chat_enabled=True, llm_governance_enabled=True, use_unified_chat_api=True)

    class FakeGov:
        skipped = True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr("pallas.product.llm.client.LlmChatGovernance", lambda **kwargs: FakeGov())

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-2",
            session_id="sess-2",
            user_text="你好",
            system_prompt="system",
            bot_id=1,
            group_id=2,
            user_id=3,
            task="llm_chat",
        ),
        cfg=cfg,
    )
    assert result.ok is False
    assert result.status == "busy"
