from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.chat_queue import clear_chat_queue_for_tests, stash_pending_chat


@pytest.mark.asyncio
async def test_pending_chat_is_consumed_after_current_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import chat_message

    clear_chat_queue_for_tests()
    event = object()
    prepare = AsyncMock()
    monkeypatch.setattr(chat_message, "prepare_and_submit_llm_chat_turn", prepare)
    stash_pending_chat(1, 2, 3, "第二个问题", message_id=22, event=event, is_to_me=True, speak_trigger="to_me")

    chat_message.schedule_pending_chat(
        bot=SimpleNamespace(self_id="1"),
        event=object(),
        group_id=2,
        user_id=3,
        llm_cfg=object(),
        chat_cfg=object(),
        delay=0,
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    prepare.assert_awaited_once()
    kwargs = prepare.await_args.kwargs
    assert kwargs["event"] is event
    assert kwargs["plain"] == "第二个问题"
    assert kwargs["message_id"] == 22
    clear_chat_queue_for_tests()
