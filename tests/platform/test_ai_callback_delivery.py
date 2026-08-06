from __future__ import annotations

from nonebot.adapters.onebot.v11 import Message

from pallas.core.platform.ai_callback.delivery import build_group_text_message
from pallas.product.llm import delivery as llm_delivery


def test_build_group_text_message_keeps_plain_text_plain() -> None:
    message = build_group_text_message("收到")

    assert message == "收到"


def test_build_group_text_message_can_quote_or_mention_a_member() -> None:
    quoted = build_group_text_message("收到", reply_to_message_id=123)
    mentioned = build_group_text_message("收到", at_user_id=456)

    assert isinstance(quoted, Message)
    assert quoted[0].type == "reply"
    assert quoted[0].data["id"] == "123"
    assert mentioned[0].type == "at"
    assert mentioned[0].data["qq"] == "456"


def test_llm_mention_delivery_requires_multi_party_and_respects_group_cooldown(monkeypatch) -> None:
    monkeypatch.setattr(llm_delivery, "_MENTION_LAST_SENT_AT", {})
    task = {
        "task_type": "llm_chat",
        "reply_delivery_style": "MENTION",
        "has_multi_party_overlap": True,
        "user_id": 456,
    }

    assert llm_delivery.resolve_llm_reply_delivery(
        task,
        group_id=123,
        mention_cooldown_sec=900,
        now=1000,
    ) == (None, 456)
    llm_delivery.note_llm_reply_mention_sent(123, now=1000)
    assert llm_delivery.resolve_llm_reply_delivery(
        task,
        group_id=123,
        mention_cooldown_sec=900,
        now=1001,
    ) == (None, None)
    assert llm_delivery.resolve_llm_reply_delivery(
        {**task, "has_multi_party_overlap": False},
        group_id=123,
        mention_cooldown_sec=900,
        now=2000,
    ) == (None, None)
