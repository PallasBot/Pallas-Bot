"""「不可以」禁言命令不能被 LLM 直连处理器吞掉，需回退 matcher 触发撤回与禁言。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.core.platform.message_runtime.models import MessageContext


def _context(plain: str, *, to_me: bool = True) -> MessageContext:
    return MessageContext(
        ingress_id="i-1",
        bot_id=1,
        group_id=2,
        message_id=3,
        plain_text=plain,
        raw_text=plain,
        is_to_me=to_me,
        command_traffic=False,
        route_modules=frozenset(),
    )


def _event(plain: str, *, reply: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        get_plaintext=lambda: plain,
        get_message=lambda: plain,
        reply=SimpleNamespace(message_id=100, message="目标消息") if reply else None,
    )


async def _noop_llm_chat(*_a, **_k) -> None:
    return None


@pytest.mark.asyncio
async def test_llm_direct_handler_yields_ban_reply_to_matchers(monkeypatch) -> None:
    from packages.llm_chat.message_runtime_handler import LlmChatDirectHandler

    handled = []
    monkeypatch.setattr(
        "packages.llm_chat.message_runtime_handler.handle_llm_chat",
        lambda *a, **k: handled.append(True) or _noop_llm_chat(),
    )
    handler = LlmChatDirectHandler()
    outcome = await handler.handle(_context("不可以"), bot=object(), event=_event("不可以"))
    assert outcome.fallback_to_matcher is True
    assert not handled, "「不可以」不应提交 LLM 闲聊"


@pytest.mark.asyncio
async def test_llm_direct_handler_yields_ban_latest_to_matchers(monkeypatch) -> None:
    from packages.llm_chat.message_runtime_handler import LlmChatDirectHandler

    handled = []
    monkeypatch.setattr(
        "packages.llm_chat.message_runtime_handler.handle_llm_chat",
        lambda *a, **k: handled.append(True) or _noop_llm_chat(),
    )
    handler = LlmChatDirectHandler()
    outcome = await handler.handle(_context("不可以发这个"), bot=object(), event=_event("不可以发这个"))
    assert outcome.fallback_to_matcher is True
    assert not handled


@pytest.mark.asyncio
async def test_llm_direct_handler_still_handles_normal_to_me_chat(monkeypatch) -> None:
    from packages.llm_chat.message_runtime_handler import LlmChatDirectHandler

    handled = []
    monkeypatch.setattr(
        "packages.llm_chat.message_runtime_handler.handle_llm_chat",
        lambda *a, **k: handled.append(True) or _noop_llm_chat(),
    )
    handler = LlmChatDirectHandler()
    outcome = await handler.handle(_context("讲个笑话"), bot=object(), event=_event("讲个笑话"))
    assert outcome.handled is True
    assert outcome.fallback_to_matcher is False
    assert handled, "普通 @ 闲聊仍应走 LLM"


def test_planner_routes_to_me_non_command_to_llm_handler() -> None:
    """规划器把普通 @ 闲聊路由给 llm_chat；禁言命令由 handler 内回退 matcher 兜底。"""
    from packages.drink.direct import DrinkDirectHandler
    from packages.greeting.direct import CallMeDirectHandler
    from packages.help.direct import HelpDirectHandler
    from packages.llm_chat.message_runtime_handler import LlmChatDirectHandler
    from packages.pb_core.direct import ConsoleDirectHandler, PluginsDirectHandler, StatusDirectHandler
    from packages.repeater.message_runtime_handler import RepeaterDirectHandler
    from pallas.core.platform.message_runtime.handlers import RuntimeHandlerRegistry
    from pallas.core.platform.message_runtime.planner import MessagePlanner

    registry = RuntimeHandlerRegistry()
    for handler in (
        DrinkDirectHandler(),
        CallMeDirectHandler(),
        HelpDirectHandler(),
        StatusDirectHandler(),
        ConsoleDirectHandler(),
        PluginsDirectHandler(),
        RepeaterDirectHandler(),
        LlmChatDirectHandler(),
    ):
        registry.register(handler)

    plan = MessagePlanner(registry).plan(_context("讲个笑话", to_me=True))
    assert plan.kind == "direct"
    assert plan.handler_ids == ("llm_chat.message",)
