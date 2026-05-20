import pytest

from src.common.multi_bot_group import (
    claim_group_handler,
    cross_bot_group_message_key,
    cross_bot_message_signature,
    normalize_group_plaintext,
    normalize_group_raw_message,
    normalize_message_time,
    try_acquire_group_broadcast_slot,
    try_begin_group_draw_cheer,
    try_begin_group_owned_gate,
    try_claim_cross_bot_message_memory,
)


def test_normalize_group_raw_message_matches_chatdata_pattern() -> None:
    raw = "prefix.image,subtype=9]"
    assert normalize_group_raw_message(raw) == "prefix.image]"


def test_cross_bot_key_same_plaintext_different_raw_cq() -> None:
    gid, uid, text, t = 12345, 999, "牛牛画画 一只羊", 1746358610
    raw_a = f"{text}[CQ:image,file=aaa,url=https://a.example/x]"
    raw_b = f"{text}[CQ:image,file=bbb,url=https://b.example/y]"
    k_plain = cross_bot_group_message_key(gid, uid, text, t, use_plaintext=True)
    assert cross_bot_group_message_key(gid, uid, raw_a, t, use_plaintext=False) != k_plain
    assert cross_bot_group_message_key(gid, uid, raw_b, t, use_plaintext=False) != k_plain
    assert k_plain == cross_bot_group_message_key(gid, uid, text, t, use_plaintext=True)


def test_cross_bot_signature_ms_and_sec_match() -> None:
    gid, uid, body = 1, 2, "牛牛画画"
    assert cross_bot_message_signature(gid, uid, body, 1746358610) == cross_bot_message_signature(
        gid, uid, body, 1746358610000
    )


def test_normalize_plaintext_collapses_whitespace() -> None:
    assert normalize_group_plaintext("牛牛画画  一只羊") == "牛牛画画 一只羊"


@pytest.mark.asyncio
async def test_cross_bot_memory_claim_only_one_bot() -> None:
    gid, uid, body, t = 12345, 999, "牛牛画画 测试", 100
    assert await try_claim_cross_bot_message_memory("pallas_image", gid, uid, body, t, 111) is True
    assert await try_claim_cross_bot_message_memory("pallas_image", gid, uid, body, t, 222) is False
    assert await try_claim_cross_bot_message_memory("pallas_image", gid, uid, body, t, 111) is True


@pytest.mark.asyncio
async def test_draw_cheer_gate_only_one_bot() -> None:
    gid = 99999
    assert await try_begin_group_draw_cheer(gid, 111, gate_sec=5) is True
    assert await try_begin_group_draw_cheer(gid, 222, gate_sec=5) is False
    assert await try_begin_group_draw_cheer(gid, 111, gate_sec=5) is True


@pytest.mark.asyncio
async def test_owned_gate_scoped_by_plugin() -> None:
    gid = 88888
    assert await try_begin_group_owned_gate("pallas_image", gid, 111, gate_sec=5) is True
    assert await try_begin_group_owned_gate("duel", gid, 222, gate_sec=5) is True


@pytest.mark.asyncio
async def test_broadcast_slot_first_wins() -> None:
    gid = 77777
    assert await try_acquire_group_broadcast_slot("duel", gid, ttl_sec=5) is True
    assert await try_acquire_group_broadcast_slot("duel", gid, ttl_sec=5) is False


@pytest.mark.asyncio
async def test_claim_group_handler_non_group_passes() -> None:
    from unittest.mock import MagicMock

    event = MagicMock()
    assert await claim_group_handler("maa", event, 111) is True
