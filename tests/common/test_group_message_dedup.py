from pathlib import Path

import pytest

from pallas.core.platform.multi_bot import claim as claim_mod
from pallas.core.platform.multi_bot.group import (
    claim_group_handler,
    cross_bot_group_message_key,
    cross_bot_message_signature,
    normalize_group_plaintext,
    normalize_group_raw_message,
    try_acquire_group_broadcast_slot,
    try_begin_group_draw_cheer,
    try_begin_group_owned_gate,
    try_claim_cross_bot_message,
    try_claim_cross_bot_message_memory,
    try_claim_group_message_once,
)
from pallas.core.platform.shard.registry import config as shard_cfg


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


def test_cross_bot_signature_ignores_message_time() -> None:
    gid, uid, body = 1, 2, "牛牛画画"
    assert cross_bot_message_signature(gid, uid, body, 1746358610) == cross_bot_message_signature(
        gid, uid, body, 1746358610000
    )
    assert cross_bot_message_signature(gid, uid, body, 100) == cross_bot_message_signature(gid, uid, body, 101)
    assert cross_bot_group_message_key(gid, uid, body, 100) == cross_bot_group_message_key(gid, uid, body, 101)


def test_cross_bot_key_includes_message_time_when_requested() -> None:
    gid, uid, body = 733291779, 3023094357, "八角笼牛"
    k1 = cross_bot_group_message_key(gid, uid, body, 100, include_message_time=True)
    k2 = cross_bot_group_message_key(gid, uid, body, 101, include_message_time=True)
    assert k1 != k2
    assert cross_bot_group_message_key(gid, uid, body, 100) == cross_bot_group_message_key(gid, uid, body, 101)


def test_normalize_plaintext_collapses_whitespace() -> None:
    assert normalize_group_plaintext("牛牛画画  一只羊") == "牛牛画画 一只羊"


@pytest.fixture
def claim_plugin_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "draw"
    monkeypatch.setattr(
        claim_mod,
        "plugin_data_dir",
        lambda name, create=True: root if name == "draw" else tmp_path / name,
    )
    return root


@pytest.mark.asyncio
async def test_group_message_once_single_process_skips_claim_file(
    claim_plugin_data: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    gid, uid, body, t = 12345, 999, "单进程", 100
    assert await try_claim_group_message_once("repeater_ingress", gid, uid, body, t) is True
    assert await try_claim_group_message_once("repeater_ingress", gid, uid, body, t) is False
    claims = claim_plugin_data / "message_claims"
    assert not claims.exists() or list(claims.glob("*.claim")) == []


@pytest.mark.asyncio
async def test_cross_bot_single_process_skips_claim_file(
    claim_plugin_data: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    gid, uid, body, t = 12345, 999, "单进程跨牛", 100
    assert await try_claim_cross_bot_message("draw", gid, uid, body, t, 111) is True
    assert await try_claim_cross_bot_message("draw", gid, uid, body, t, 222) is False
    claims = claim_plugin_data / "message_claims"
    assert not claims.exists() or list(claims.glob("*.claim")) == []


@pytest.mark.asyncio
async def test_group_message_once_same_sig_only_first() -> None:
    gid, uid, body, t = 12345, 999, "呃呃呃", 100
    assert await try_claim_group_message_once("repeater_ingress", gid, uid, body, t) is True
    assert await try_claim_group_message_once("repeater_ingress", gid, uid, body, t) is False
    assert await try_claim_group_message_once("repeater_ingress", gid, uid, body, t) is False


@pytest.mark.asyncio
async def test_roulette_start_once_same_user_different_message_time() -> None:
    gid, uid, body = 733291779, 3385897861, "牛牛轮盘"
    assert await try_claim_group_message_once("roulette_start", gid, uid, body, 100, include_message_time=True) is True
    assert await try_claim_group_message_once("roulette_start", gid, uid, body, 100, include_message_time=True) is False
    assert await try_claim_group_message_once("roulette_start", gid, uid, body, 101, include_message_time=True) is True


@pytest.mark.asyncio
async def test_cross_bot_memory_claim_only_one_bot() -> None:
    gid, uid, body, t = 12345, 999, "牛牛画画 测试", 100
    assert await try_claim_cross_bot_message_memory("draw", gid, uid, body, t, 111) is True
    assert await try_claim_cross_bot_message_memory("draw", gid, uid, body, t, 222) is False
    assert await try_claim_cross_bot_message_memory("draw", gid, uid, body, t, 111) is True


@pytest.mark.asyncio
async def test_cross_bot_memory_claim_same_body_different_time() -> None:
    gid, uid, body = 12345, 999, "牛牛帮助"
    assert await try_claim_cross_bot_message_memory("ingress", gid, uid, body, 100, 111) is True
    assert await try_claim_cross_bot_message_memory("ingress", gid, uid, body, 101, 222) is False


@pytest.mark.asyncio
async def test_duel_memory_claim_scoped_by_message_time() -> None:
    gid, uid, body = 733291779, 1, "八角笼牛"
    assert await try_claim_cross_bot_message_memory("duel", gid, uid, body, 100, 111, include_message_time=True)
    assert await try_claim_cross_bot_message_memory("duel", gid, uid, body, 101, 222, include_message_time=True)
    assert not await try_claim_cross_bot_message_memory("duel", gid, uid, body, 101, 111, include_message_time=True)


@pytest.mark.asyncio
async def test_draw_cheer_gate_only_one_bot() -> None:
    gid = 99999
    assert await try_begin_group_draw_cheer(gid, 111, gate_sec=5) is True
    assert await try_begin_group_draw_cheer(gid, 222, gate_sec=5) is False
    assert await try_begin_group_draw_cheer(gid, 111, gate_sec=5) is True


@pytest.mark.asyncio
async def test_owned_gate_scoped_by_plugin() -> None:
    gid = 88888
    assert await try_begin_group_owned_gate("draw", gid, 111, gate_sec=5) is True
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
