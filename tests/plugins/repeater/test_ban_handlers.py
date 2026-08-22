from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "reason"),
    [
        ("handle_ban_reply", "not_allowed_reply"),
        ("handle_ban_latest", "not_allowed_latest"),
    ],
)
async def test_message_ban_handlers_apply_llm_negative_feedback_before_chat_ban(
    monkeypatch,
    handler_name,
    reason,
) -> None:
    from packages.repeater.handlers import ban

    events: list[str] = []

    async def record_feedback(**_kwargs) -> None:
        events.append("feedback")

    async def record_ban(*_args) -> bool:
        events.append("ban")
        return True

    feedback = AsyncMock(side_effect=record_feedback)
    chat_ban = AsyncMock(side_effect=record_ban)
    finish_ack = AsyncMock()
    monkeypatch.setattr(ban, "apply_llm_negative_feedback_for_bot_message", feedback)
    monkeypatch.setattr(ban.Chat, "ban", chat_ban)
    monkeypatch.setattr(ban, "resolve_ban_reply_raw", AsyncMock(return_value="target"))
    monkeypatch.setattr(ban, "finish_ban_ack", finish_ack)
    bot = SimpleNamespace(delete_msg=AsyncMock())
    event = SimpleNamespace(
        self_id=10001,
        group_id=20001,
        user_id=30001,
        reply=SimpleNamespace(message_id=40001),
    )

    await getattr(ban, handler_name)(bot, event, {})

    feedback.assert_awaited_once_with(
        bot_id="10001",
        group_id="20001",
        bot_message_id="40001",
        actor_id="30001",
        reason=reason,
    )
    chat_ban.assert_awaited_once()
    bot.delete_msg.assert_awaited_once_with(message_id=40001)
    finish_ack.assert_awaited_once()
    assert events == ["feedback", "ban"]


@pytest.mark.asyncio
async def test_recalled_ban_handler_applies_llm_negative_feedback_before_chat_ban(monkeypatch) -> None:
    from packages.repeater.handlers import ban

    events: list[str] = []

    async def record_feedback(**_kwargs) -> None:
        events.append("feedback")

    async def record_ban(*_args) -> bool:
        events.append("ban")
        return True

    feedback = AsyncMock(side_effect=record_feedback)
    chat_ban = AsyncMock(side_effect=record_ban)
    finish_ack = AsyncMock()
    monkeypatch.setattr(ban, "apply_llm_negative_feedback_for_bot_message", feedback)
    monkeypatch.setattr(ban.Chat, "ban", chat_ban)
    monkeypatch.setattr(ban, "finish_ban_ack", finish_ack)
    bot = SimpleNamespace(get_msg=AsyncMock(return_value={"message": "target"}))
    event = SimpleNamespace(self_id=10001, group_id=20001, message_id=40001, operator_id=30001)

    await ban.handle_ban_recalled(bot, event, {})

    feedback.assert_awaited_once_with(
        bot_id="10001",
        group_id="20001",
        bot_message_id="40001",
        actor_id="30001",
        reason="admin_recall",
    )
    chat_ban.assert_awaited_once()
    finish_ack.assert_awaited_once()
    assert events == ["feedback", "ban"]


@pytest.mark.asyncio
async def test_reply_feedback_failure_does_not_block_ban(monkeypatch) -> None:
    from packages.repeater.handlers import ban

    feedback = AsyncMock(side_effect=RuntimeError("ledger unavailable"))
    chat_ban = AsyncMock(return_value=False)
    monkeypatch.setattr(ban, "apply_llm_negative_feedback_for_bot_message", feedback)
    monkeypatch.setattr(ban.Chat, "ban", chat_ban)
    monkeypatch.setattr(ban, "resolve_ban_reply_raw", AsyncMock(return_value="target"))
    bot = SimpleNamespace(delete_msg=AsyncMock())
    event = SimpleNamespace(
        self_id=10001,
        group_id=20001,
        user_id=30001,
        reply=SimpleNamespace(message_id=40001),
    )

    await ban.handle_ban_reply(bot, event, {})

    chat_ban.assert_awaited_once()
    bot.delete_msg.assert_awaited_once_with(message_id=40001)


@pytest.mark.asyncio
async def test_recalled_feedback_failure_does_not_block_ban(monkeypatch) -> None:
    from packages.repeater.handlers import ban

    feedback = AsyncMock(side_effect=RuntimeError("ledger unavailable"))
    chat_ban = AsyncMock(return_value=False)
    finish_ack = AsyncMock()
    monkeypatch.setattr(ban, "apply_llm_negative_feedback_for_bot_message", feedback)
    monkeypatch.setattr(ban.Chat, "ban", chat_ban)
    monkeypatch.setattr(ban, "finish_ban_ack", finish_ack)
    bot = SimpleNamespace(get_msg=AsyncMock(return_value={"message": "target"}))
    event = SimpleNamespace(self_id=10001, group_id=20001, message_id=40001, operator_id=30001)

    await ban.handle_ban_recalled(bot, event, {})

    chat_ban.assert_awaited_once()
    finish_ack.assert_not_awaited()


@pytest.mark.asyncio
async def test_latest_feedback_failure_does_not_block_ban(monkeypatch) -> None:
    from packages.repeater.handlers import ban

    feedback = AsyncMock(side_effect=RuntimeError("ledger unavailable"))
    chat_ban = AsyncMock(return_value=False)
    finish_ack = AsyncMock()
    monkeypatch.setattr(ban, "apply_llm_negative_feedback_for_bot_message", feedback)
    monkeypatch.setattr(ban.Chat, "ban", chat_ban)
    monkeypatch.setattr(ban, "finish_ban_ack", finish_ack)
    bot = SimpleNamespace(delete_msg=AsyncMock())
    event = SimpleNamespace(
        self_id=10001,
        group_id=20001,
        user_id=30001,
        reply=SimpleNamespace(message_id=40001),
    )

    await ban.handle_ban_latest(bot, event, {})

    chat_ban.assert_awaited_once()
    bot.delete_msg.assert_awaited_once_with(message_id=40001)
    finish_ack.assert_not_awaited()
