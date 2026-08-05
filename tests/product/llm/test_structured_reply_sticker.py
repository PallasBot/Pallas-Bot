from __future__ import annotations

from pallas.product.llm.structured_reply import parse_structured_reply


def test_structured_reply_keeps_send_sticker_request() -> None:
    reply = parse_structured_reply('{"reply":"行，我收下了。","sticker":"send"}')

    assert reply.reply == "行，我收下了。"
    assert reply.sticker == "send"


def test_structured_reply_rejects_unknown_sticker_request() -> None:
    reply = parse_structured_reply('{"reply":"行。","sticker":"cat"}')

    assert reply.sticker == "none"
