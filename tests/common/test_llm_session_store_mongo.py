from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.session_store import (
    append_llm_message,
    build_llm_chat_messages,
    clear_llm_messages,
    clear_user_llm_messages,
    compact_user_llm_history_with_summary,
    get_llm_history_session_detail,
    is_llm_session_store_available,
    list_group_ambient_messages,
    list_llm_history_sessions,
    list_user_llm_messages,
)


def _patch_mongo_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.foundation.db.runtime.is_postgresql_backend",
        lambda _backend=None: False,
    )
    monkeypatch.setattr(
        "pallas.core.foundation.db.runtime.is_mongodb_backend",
        lambda _backend=None: True,
    )
    monkeypatch.setattr(
        "pallas.core.foundation.db.runtime_storage_ready",
        lambda _backend=None: True,
    )
    clock = {"t": 1_700_000_000}

    def fake_time() -> int:
        clock["t"] += 1
        return clock["t"]

    monkeypatch.setattr("pallas.product.llm.session_store_mongo.time.time", fake_time)


@pytest.mark.asyncio
async def test_mongo_llm_session_user_window_and_ambient(beanie_fixture, monkeypatch) -> None:
    clear_llm_config_cache()
    _patch_mongo_backend(monkeypatch)
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=2,
        llm_session_group_window=2,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    assert is_llm_session_store_available() is True

    for index in range(3):
        assert await append_llm_message(10001, 20002, 30003, "user", f"a-{index}") is True
    for index in range(3):
        assert await append_llm_message(10001, 20002, 40004, "user", f"b-{index}") is True

    user_a = await list_user_llm_messages(10001, 20002, 30003)
    user_b = await list_user_llm_messages(10001, 20002, 40004)
    assert [turn.content for turn in user_a] == ["a-1", "a-2"]
    assert [turn.content for turn in user_b] == ["b-1", "b-2"]

    ambient = await list_group_ambient_messages(10001, 20002)
    # group_window=2 → 群内按时间最近 2 条（trim 后剩 a-1/a-2/b-1/b-2）
    assert len(ambient) == 2
    assert {turn.content for turn in ambient} == {"b-1", "b-2"}


@pytest.mark.asyncio
async def test_mongo_build_llm_chat_messages_user_thread_and_ambient(beanie_fixture, monkeypatch) -> None:
    clear_llm_config_cache()
    _patch_mongo_backend(monkeypatch)
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_session_enabled=True,
        llm_session_user_window=8,
        llm_session_group_window=4,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)

    from pallas.product.llm.kernel.memory_governance import can_read_runtime_state

    assert can_read_runtime_state(cfg) is True

    await append_llm_message(1, 100, 200, "user", "other-user-msg")
    await append_llm_message(1, 100, 200, "assistant", "reply-to-other")
    await append_llm_message(1, 100, 300, "user", "my-old")
    await append_llm_message(1, 100, 300, "assistant", "my-reply")

    messages = await build_llm_chat_messages(1, 100, 300, "my-new", cfg=cfg)
    assert messages[-1].role == "user"
    assert "my-new" in messages[-1].content
    joined = "\n".join(item.content for item in messages)
    assert "群环境摘录" in joined, joined
    assert "my-old" in joined


@pytest.mark.asyncio
async def test_mongo_clear_and_history(beanie_fixture, monkeypatch) -> None:
    clear_llm_config_cache()
    _patch_mongo_backend(monkeypatch)
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=20,
        llm_session_group_window=20,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)

    await append_llm_message(10, 100, 200, "user", "u200-1")
    await append_llm_message(10, 100, 200, "assistant", "a200-1")
    await append_llm_message(10, 100, 300, "user", "u300-1")
    await append_llm_message(10, 100, 300, "assistant", "a300-1")

    sessions = await list_llm_history_sessions(bot_id=10, group_id=100, limit=10)
    assert [row.user_id for row in sessions] == [300, 200]
    assert sessions[0].last_content == "a300-1"
    assert sessions[0].turn_count == 2

    detail = await get_llm_history_session_detail(bot_id=10, group_id=100, user_id=200, limit=10)
    assert detail is not None
    assert [turn.content for turn in detail.turns] == ["u200-1", "a200-1"]

    assert await clear_user_llm_messages(10, 100, 200) == 2
    assert await list_user_llm_messages(10, 100, 200) == []
    assert await clear_llm_messages(10, 100) == 2


@pytest.mark.asyncio
async def test_mongo_compact_user_history(beanie_fixture, monkeypatch) -> None:
    clear_llm_config_cache()
    _patch_mongo_backend(monkeypatch)
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=20,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)

    for index in range(5):
        await append_llm_message(1, 10, 20, "user", f"msg-{index}")
    assert await compact_user_llm_history_with_summary(
        1,
        10,
        20,
        "summary-text",
        keep_messages=2,
        cfg=cfg,
    )
    turns = await list_user_llm_messages(1, 10, 20, limit=20)
    assert any("此前对话摘要" in turn.content and "summary-text" in turn.content for turn in turns)
    assert len(turns) == 3
