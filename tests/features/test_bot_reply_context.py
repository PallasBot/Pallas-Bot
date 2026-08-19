from __future__ import annotations

import time

from pallas.product.llm.bot_reply_context import (
    clear_bot_reply_context_for_tests,
    lookup_bot_reply_context,
    record_bot_reply_context,
)


def test_reply_context_matches_exact_group_bot_and_message() -> None:
    clear_bot_reply_context_for_tests()
    record_bot_reply_context(group_id=20, bot_id=10, message_id=30, text="复读的原话")

    assert lookup_bot_reply_context(group_id=20, bot_id=10, message_id=30) == "复读的原话"
    assert lookup_bot_reply_context(group_id=20, bot_id=11, message_id=30) is None
    assert lookup_bot_reply_context(group_id=21, bot_id=10, message_id=30) is None
    assert lookup_bot_reply_context(group_id=20, bot_id=10, message_id=31) is None


def test_reply_context_expires(monkeypatch) -> None:
    clear_bot_reply_context_for_tests()
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    record_bot_reply_context(group_id=20, bot_id=10, message_id=30, text="会过期")
    now[0] += 601

    assert lookup_bot_reply_context(group_id=20, bot_id=10, message_id=30) is None


def test_reply_context_ignores_missing_message_id_and_empty_text() -> None:
    clear_bot_reply_context_for_tests()
    record_bot_reply_context(group_id=20, bot_id=10, message_id=None, text="没有消息 ID")
    record_bot_reply_context(group_id=20, bot_id=10, message_id=30, text=" ")

    assert lookup_bot_reply_context(group_id=20, bot_id=10, message_id=30) is None
