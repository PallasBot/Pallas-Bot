from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.core.foundation.db.repository_pg import LlmChatMessageRow, get_session
from pallas.product.llm.behavior import BehaviorAction, BehaviorOutcome, BehaviorPattern, BehaviorRun, BehaviorScene
from pallas.product.llm.behavior_store import (
    append_behavior_run,
    list_behavior_patterns,
    list_behavior_runs,
    save_behavior_patterns,
)
from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.injection_feedback import apply_negative_outcome
from pallas.product.llm.session_models import LlmChatTurn
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
    read_user_llm_compaction_snapshot,
    sanitize_stored_content,
    user_ttl_seconds,
)


@pytest.fixture(scope="module", autouse=True)
def disable_feedback_trigger_backfill() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "pallas.product.llm.feedback_embedding_cache.schedule_feedback_trigger_backfill",
            lambda: None,
        )
        yield


def test_sanitize_stored_content_strips_control_chars() -> None:
    raw = "hello\x00world"
    assert sanitize_stored_content("user", raw, max_len=200) == "helloworld"


def test_sanitize_stored_content_strips_vision_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("LLM_SESSION_STRIP_VISION_ENABLED", "1")
    raw = "[CQ:image,file=abc] 看看"
    assert sanitize_stored_content("user", raw, max_len=200) == "[图片] 看看"
    assert sanitize_stored_content("assistant", raw, max_len=200) == raw


def test_user_ttl_private_vs_group() -> None:
    cfg = LlmConfig()
    assert user_ttl_seconds(12345, cfg) == 0
    assert user_ttl_seconds(0, cfg) == 259200
    assert user_ttl_seconds(None, cfg) == 259200


@pytest.mark.asyncio
async def test_llm_session_store_noop_when_disabled(monkeypatch) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("LLM_SESSION_ENABLED", "0")
    assert is_llm_session_store_available() is False
    ok = await append_llm_message(1, 100, 200, "user", "hi")
    assert ok is False
    assert await list_user_llm_messages(1, 100, 200) == []


@pytest.mark.asyncio
async def test_llm_session_user_window_independent(pg_engine, monkeypatch) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("LLM_SESSION_ENABLED", "1")
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=2,
        llm_session_group_window=2,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    for index in range(3):
        assert await append_llm_message(10001, 20002, 30003, "user", f"a-{index}") is True
    for index in range(3):
        assert await append_llm_message(10001, 20002, 40004, "user", f"b-{index}") is True

    user_a = await list_user_llm_messages(10001, 20002, 30003)
    user_b = await list_user_llm_messages(10001, 20002, 40004)
    assert [turn.content for turn in user_a] == ["a-1", "a-2"]
    assert [turn.content for turn in user_b] == ["b-1", "b-2"]

    ambient = await list_group_ambient_messages(10001, 20002)
    assert len(ambient) == 2
    assert {turn.content for turn in ambient} == {"b-1", "b-2"}


@pytest.mark.asyncio
async def test_build_llm_chat_messages_skips_history_when_policy_disabled(pg_engine, monkeypatch) -> None:
    clear_llm_config_cache()
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_session_enabled=False,
        llm_session_user_window=8,
        llm_session_group_window=4,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    await append_llm_message(1, 100, 300, "user", "my-old")
    await append_llm_message(1, 100, 300, "assistant", "my-reply")

    messages = await build_llm_chat_messages(1, 100, 300, "my-new", cfg=cfg)
    assert len(messages) == 1
    assert "my-new" in messages[0].content
    assert not any("my-old" in item.content for item in messages)


@pytest.mark.asyncio
async def test_build_llm_chat_messages_user_thread_and_ambient(pg_engine, monkeypatch) -> None:
    clear_llm_config_cache()
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_session_enabled=True,
        llm_session_user_window=8,
        llm_session_group_window=4,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    await append_llm_message(1, 100, 200, "user", "other-user-msg")
    await append_llm_message(1, 100, 200, "assistant", "reply-to-other")
    await append_llm_message(1, 100, 300, "user", "my-old")
    await append_llm_message(1, 100, 300, "assistant", "my-reply")

    messages = await build_llm_chat_messages(1, 100, 300, "my-new", cfg=cfg)
    assert messages[-1].role == "user"
    assert "my-new" in messages[-1].content
    assert any("群环境摘录" in item.content for item in messages)
    assert any("my-old" in item.content for item in messages)


@pytest.mark.asyncio
async def test_build_llm_chat_messages_returns_exact_selected_ambient_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(llm_session_enabled=True, llm_session_group_window=4)
    ambient = [
        LlmChatTurn(role="user", content="群友消息", user_id=200, created_at=11),
        LlmChatTurn(role="assistant", content="机器人回复", user_id=10001, created_at=12),
        LlmChatTurn(role="user", content="当前用户消息", user_id=300, created_at=13),
    ]
    monkeypatch.setattr("pallas.product.llm.session_store.can_read_runtime_state", lambda _cfg: True)
    monkeypatch.setattr(
        "pallas.product.llm.session_store.list_group_ambient_messages",
        AsyncMock(return_value=ambient),
    )
    monkeypatch.setattr("pallas.product.llm.session_store.list_user_llm_messages", AsyncMock(return_value=[]))
    selected: list[dict[str, object]] = []

    messages = await build_llm_chat_messages(
        10001,
        100,
        300,
        "当前提问",
        cfg=cfg,
        ambient_turns_out=selected,
    )

    assert "群环境摘录" in messages[0].content
    assert [item["user_id"] for item in selected] == [200, 10001]
    assert all(str(item["turn_id"]).startswith("ambient:") for item in selected)
    assert all(len(str(item["text_hash"])) == 64 for item in selected)
    assert [item["text_preview"] for item in selected] == ["群友消息", "机器人回复"]
    json.dumps(selected)


@pytest.mark.asyncio
async def test_build_llm_chat_messages_filters_blacklisted_ambient_before_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    cfg = LlmConfig(llm_session_enabled=True, llm_session_group_window=4)
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    apply_negative_outcome(
        outcome_id="ambient-filter",
        bot_id=10001,
        group_id=100,
        reply_text="别提茄子",
        injection_snapshot={"ambient_turns": [{"turn_id": "old", "text_preview": "茄子又来了"}]},
        now=1,
    )
    ambient = [
        LlmChatTurn(role="user", content="茄子又来了", user_id=200, created_at=11),
        LlmChatTurn(role="user", content="正常消息", user_id=201, created_at=12),
    ]
    monkeypatch.setattr("pallas.product.llm.session_store.can_read_runtime_state", lambda _cfg: True)
    monkeypatch.setattr(
        "pallas.product.llm.session_store.list_group_ambient_messages",
        AsyncMock(return_value=ambient),
    )
    monkeypatch.setattr("pallas.product.llm.session_store.list_user_llm_messages", AsyncMock(return_value=[]))
    selected: list[dict[str, object]] = []

    messages = await build_llm_chat_messages(10001, 100, 300, "当前提问", cfg=cfg, ambient_turns_out=selected)

    assert "正常消息" in messages[0].content
    assert "茄子又来了" not in messages[0].content
    assert [item["text_preview"] for item in selected] == ["正常消息"]


@pytest.mark.asyncio
async def test_build_llm_chat_messages_backfills_own_recent_pair_when_ambient_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(llm_session_enabled=True, llm_session_group_window=4)
    ambient = [
        LlmChatTurn(role="user", content="旧提问", user_id=300, created_at=1001),
        LlmChatTurn(role="assistant", content="旧回复", user_id=300, created_at=1002),
        LlmChatTurn(role="user", content="新提问", user_id=300, created_at=1003),
        LlmChatTurn(role="assistant", content="新回复", user_id=300, created_at=1004),
    ]
    monkeypatch.setattr("pallas.product.llm.session_store.can_read_runtime_state", lambda _cfg: True)
    monkeypatch.setattr(
        "pallas.product.llm.session_store.list_group_ambient_messages",
        AsyncMock(return_value=ambient),
    )
    monkeypatch.setattr("pallas.product.llm.session_store.list_user_llm_messages", AsyncMock(return_value=[]))
    selected: list[dict[str, object]] = []

    await build_llm_chat_messages(10001, 100, 300, "当前提问", cfg=cfg, ambient_turns_out=selected)

    assert [item["user_id"] for item in selected] == [300, 300]
    assert [item["text_preview"] for item in selected] == ["新提问", "新回复"]


@pytest.mark.asyncio
async def test_build_llm_chat_messages_backfills_own_pair_keeps_other_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(llm_session_enabled=True, llm_session_group_window=4)
    ambient = [
        LlmChatTurn(role="user", content="自己旧消息", user_id=300, created_at=1001),
        LlmChatTurn(role="user", content="群友消息", user_id=200, created_at=1002),
        LlmChatTurn(role="user", content="自己新提问", user_id=300, created_at=1003),
        LlmChatTurn(role="assistant", content="自己新回复", user_id=300, created_at=1004),
    ]
    monkeypatch.setattr("pallas.product.llm.session_store.can_read_runtime_state", lambda _cfg: True)
    monkeypatch.setattr(
        "pallas.product.llm.session_store.list_group_ambient_messages",
        AsyncMock(return_value=ambient),
    )
    monkeypatch.setattr("pallas.product.llm.session_store.list_user_llm_messages", AsyncMock(return_value=[]))
    selected: list[dict[str, object]] = []

    await build_llm_chat_messages(10001, 100, 300, "当前提问", cfg=cfg, ambient_turns_out=selected)

    assert [item["text_preview"] for item in selected] == ["自己新提问", "自己新回复", "群友消息"]
    assert [item["user_id"] for item in selected] == [300, 300, 200]


@pytest.mark.asyncio
async def test_build_llm_chat_messages_keeps_ambient_when_feedback_filter_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(llm_session_enabled=True, llm_session_group_window=4)
    ambient = [LlmChatTurn(role="user", content="保留消息", user_id=200, created_at=11)]
    monkeypatch.setattr("pallas.product.llm.session_store.can_read_runtime_state", lambda _cfg: True)
    monkeypatch.setattr(
        "pallas.product.llm.session_store.list_group_ambient_messages",
        AsyncMock(return_value=ambient),
    )
    monkeypatch.setattr("pallas.product.llm.session_store.list_user_llm_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "pallas.product.llm.injection_feedback.filter_ambient_turns",
        lambda *_args: (_ for _ in ()).throw(OSError("ledger unavailable")),
    )

    messages = await build_llm_chat_messages(10001, 100, 300, "当前提问", cfg=cfg)

    assert "保留消息" in messages[0].content


@pytest.mark.asyncio
async def test_build_llm_chat_messages_excludes_ambient_turn_clipped_from_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(llm_session_enabled=True, llm_session_group_window=4, user_message_max_len=64)
    ambient = [
        LlmChatTurn(role="user", content="甲" * 54, user_id=200, created_at=11),
        LlmChatTurn(role="user", content="乙乙乙", user_id=201, created_at=12),
    ]
    monkeypatch.setattr("pallas.product.llm.session_store.can_read_runtime_state", lambda _cfg: True)
    monkeypatch.setattr(
        "pallas.product.llm.session_store.list_group_ambient_messages",
        AsyncMock(return_value=ambient),
    )
    monkeypatch.setattr("pallas.product.llm.session_store.list_user_llm_messages", AsyncMock(return_value=[]))
    selected: list[dict[str, object]] = []

    await build_llm_chat_messages(10001, 100, 300, "当前提问", cfg=cfg, ambient_turns_out=selected)

    assert [item["user_id"] for item in selected] == [200]


@pytest.mark.asyncio
async def test_build_llm_chat_messages_uses_full_session_window_without_ambient(pg_engine, monkeypatch) -> None:
    clear_llm_config_cache()
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_session_enabled=True,
        llm_session_user_window=8,
        llm_session_group_window=4,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    await append_llm_message(1, 100, 200, "user", "other-user-msg")
    await append_llm_message(1, 100, 200, "assistant", "reply-to-other")
    await append_llm_message(1, 100, 300, "user", "old-user")
    await append_llm_message(1, 100, 300, "assistant", "old-reply")
    await append_llm_message(1, 100, 300, "user", "story-user")
    await append_llm_message(1, 100, 300, "assistant", "story-reply")

    messages = await build_llm_chat_messages(
        1,
        100,
        300,
        "继续讲",
        cfg=cfg,
        include_history=True,
        include_group_ambient=False,
    )

    assert [item.role for item in messages] == ["user", "assistant", "user", "assistant", "user"]
    assert "old-user" in messages[0].content
    assert messages[1].content == "old-reply"
    assert "story-user" in messages[2].content
    assert messages[3].content == "story-reply"
    assert "继续讲" in messages[4].content
    assert not any("群环境摘录" in item.content for item in messages)


@pytest.mark.asyncio
async def test_build_llm_chat_messages_forwards_full_window_history_without_ambient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_window=8, llm_session_group_window=4)
    history = [
        LlmChatTurn(role="user", content="story-user", user_id=300, created_at=1),
        LlmChatTurn(role="assistant", content="story-reply", user_id=300, created_at=2),
    ]
    history_mock = AsyncMock(return_value=history)
    ambient_mock = AsyncMock(return_value=[])
    monkeypatch.setattr("pallas.product.llm.session_store.can_read_runtime_state", lambda _cfg: True)
    monkeypatch.setattr("pallas.product.llm.session_store.list_user_llm_messages", history_mock)
    monkeypatch.setattr("pallas.product.llm.session_store.list_group_ambient_messages", ambient_mock)

    messages = await build_llm_chat_messages(
        1,
        100,
        300,
        "继续讲",
        cfg=cfg,
        include_history=True,
        include_group_ambient=False,
    )

    assert [item.role for item in messages] == ["user", "assistant", "user"]
    assert history_mock.await_args.kwargs["limit"] is None
    ambient_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_llm_chat_messages_skips_session_context_for_short_social_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_llm_config_cache()
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=8,
        llm_session_group_window=4,
    )
    ambient_mock = AsyncMock(return_value=[])
    history_mock = AsyncMock(return_value=[])
    monkeypatch.setattr("pallas.product.llm.session_store.can_read_runtime_state", lambda _cfg: True)
    monkeypatch.setattr("pallas.product.llm.session_store.list_group_ambient_messages", ambient_mock)
    monkeypatch.setattr("pallas.product.llm.session_store.list_user_llm_messages", history_mock)

    messages = await build_llm_chat_messages(1, 100, 300, "没绷住", cfg=cfg, include_history=False)

    assert len(messages) == 1
    assert messages[0].role == "user"
    assert "没绷住" in messages[0].content
    ambient_mock.assert_not_awaited()
    history_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_user_llm_messages(pg_engine, monkeypatch) -> None:
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_ttl_sec=0)
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    await append_llm_message(1, 100, 200, "user", "a")
    await append_llm_message(1, 100, 300, "user", "b")
    assert await clear_user_llm_messages(1, 100, 200) == 1
    assert await list_user_llm_messages(1, 100, 200) == []
    assert len(await list_user_llm_messages(1, 100, 300)) == 1

    assert await clear_llm_messages(1, 100) == 1


@pytest.mark.asyncio
async def test_list_llm_history_sessions_and_detail(pg_engine, monkeypatch) -> None:
    clear_llm_config_cache()
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=20,
        llm_session_group_window=20,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    await append_llm_message(10, 100, 200, "user", "u200-1")
    await append_llm_message(10, 100, 200, "assistant", "a200-1")
    await append_llm_message(10, 100, 300, "user", "u300-1")
    await append_llm_message(10, 100, 300, "assistant", "a300-1")
    await append_llm_message(10, 0, 400, "user", "private-1")

    sessions = await list_llm_history_sessions(bot_id=10, group_id=100, limit=10)
    assert [row.user_id for row in sessions] == [300, 200]
    assert sessions[0].last_content == "a300-1"
    assert sessions[0].turn_count == 2

    detail = await get_llm_history_session_detail(bot_id=10, group_id=100, user_id=200, limit=10)
    assert detail is not None
    assert detail.session.user_id == 200
    assert [turn.content for turn in detail.turns] == ["u200-1", "a200-1"]


@pytest.mark.asyncio
async def test_list_llm_history_sessions_same_timestamp_uses_latest_message_id(pg_engine, monkeypatch) -> None:
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_ttl_sec=0)
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    async with get_session() as session:
        session.add_all(
            [
                LlmChatMessageRow(
                    id=1, bot_id=10, group_id=100, user_id=200, role="user", content="a-first", created_at=1000
                ),
                LlmChatMessageRow(
                    id=2, bot_id=10, group_id=100, user_id=300, role="user", content="b-first", created_at=1000
                ),
                LlmChatMessageRow(
                    id=3, bot_id=10, group_id=100, user_id=200, role="assistant", content="a-latest", created_at=1000
                ),
                LlmChatMessageRow(
                    id=4,
                    bot_id=10,
                    group_id=100,
                    user_id=300,
                    role="assistant",
                    content="b-latest",
                    created_at=1000,
                ),
            ]
        )
        await session.commit()

    sessions = await list_llm_history_sessions(bot_id=10, group_id=100, limit=1)
    assert len(sessions) == 1
    latest = sessions[0]
    assert latest.session_key == "10:100:300"
    assert latest.turn_count == 2
    assert latest.first_created_at == 1000
    assert latest.last_created_at == 1000
    assert latest.last_role == "assistant"
    assert latest.last_content == "b-latest"


@pytest.mark.asyncio
async def test_list_llm_history_sessions_orders_by_time_not_global_message_id(pg_engine, monkeypatch) -> None:
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_ttl_sec=0)
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    async with get_session() as session:
        session.add_all(
            [
                LlmChatMessageRow(
                    id=300, bot_id=10, group_id=100, user_id=200, role="user", content="a-first", created_at=1000
                ),
                LlmChatMessageRow(
                    id=100,
                    bot_id=10,
                    group_id=100,
                    user_id=200,
                    role="assistant",
                    content="a-latest-by-time",
                    created_at=3000,
                ),
                LlmChatMessageRow(
                    id=500, bot_id=10, group_id=100, user_id=300, role="user", content="b-latest", created_at=2000
                ),
            ]
        )
        await session.commit()

    sessions = await list_llm_history_sessions(bot_id=10, group_id=100, limit=1)
    assert len(sessions) == 1
    latest = sessions[0]
    assert latest.session_key == "10:100:200"
    assert latest.turn_count == 2
    assert latest.first_created_at == 1000
    assert latest.last_created_at == 3000
    assert latest.last_role == "assistant"
    assert latest.last_content == "a-latest-by-time"


@pytest.mark.asyncio
async def test_llm_history_detail_includes_behavior_runs(pg_engine, monkeypatch, tmp_path) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=20,
        llm_session_group_window=20,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    await append_llm_message(10, 100, 200, "user", "u200-1")
    await append_llm_message(10, 100, 200, "assistant", "a200-1")
    append_behavior_run(
        BehaviorRun(
            request_id="req-1",
            bot_id=10,
            group_id=100,
            user_id=200,
            scene=BehaviorScene.PROVOCATION,
            selected_pattern_ids=["p1"],
            selected_actions=[BehaviorAction.LIGHT_TEASE_AND_CLOSE],
            final_outcome=BehaviorOutcome.NEUTRAL,
        )
    )

    detail = await get_llm_history_session_detail(bot_id=10, group_id=100, user_id=200, limit=10)
    assert detail is not None
    assert detail.behavior_runs[0]["request_id"] == "req-1"
    assert detail.behavior_runs[0]["selected_actions"] == ["light_tease_and_close"]


@pytest.mark.asyncio
async def test_llm_history_detail_auto_settles_behavior_outcome(pg_engine, monkeypatch, tmp_path) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=20,
        llm_session_group_window=20,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    run_created_at = 1_700_000_000
    monkeypatch.setattr(
        "pallas.product.llm.session_store_pg.time",
        SimpleNamespace(time=lambda: run_created_at - 1),
    )
    await append_llm_message(10, 100, 200, "user", "你又来这套")
    monkeypatch.setattr(
        "pallas.product.llm.session_store_pg.time",
        SimpleNamespace(time=lambda: run_created_at),
    )
    await append_llm_message(10, 100, 200, "assistant", "少来。")
    turns = await list_user_llm_messages(10, 100, 200, limit=10)
    user_turn = next(item for item in turns if item.role == "user")
    assistant_turn = next(item for item in turns if item.role == "assistant")
    assert user_turn.created_at == run_created_at - 1
    assert assistant_turn.created_at == run_created_at
    save_behavior_patterns([
        BehaviorPattern(
            pattern_id="p1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            success_score=0,
        )
    ])
    append_behavior_run(
        BehaviorRun(
            request_id="req-2",
            bot_id=10,
            group_id=100,
            user_id=200,
            created_at=run_created_at,
            scene=BehaviorScene.PROVOCATION,
            reply_text="少来。",
            selected_pattern_ids=["p1"],
            selected_actions=[BehaviorAction.LIGHT_TEASE_AND_CLOSE],
        )
    )
    followup_created_at = run_created_at + 1
    monkeypatch.setattr(
        "pallas.product.llm.session_store_pg.time",
        SimpleNamespace(time=lambda: followup_created_at),
    )
    await append_llm_message(10, 100, 200, "user", "哈哈那然后呢？")
    followup_turn = (await list_user_llm_messages(10, 100, 200, limit=10))[-1]
    assert followup_turn.created_at == run_created_at + 1
    assert assistant_turn.created_at < followup_turn.created_at

    detail = await get_llm_history_session_detail(bot_id=10, group_id=100, user_id=200, limit=10)
    assert detail is not None
    assert detail.behavior_runs[-1]["request_id"] == "req-2"
    assert detail.behavior_runs[-1]["final_outcome"] == BehaviorOutcome.ENGAGED
    assert detail.behavior_runs[-1]["score_delta"] == 2

    repeated_detail = await get_llm_history_session_detail(bot_id=10, group_id=100, user_id=200, limit=10)
    assert repeated_detail is not None
    assert repeated_detail.behavior_runs[-1]["final_outcome"] == BehaviorOutcome.ENGAGED
    patterns = list_behavior_patterns()
    assert patterns[0].success_score == 2
    assert patterns[0].applied_outcome_ids == ["req-2"]
    stored_run = next(item for item in list_behavior_runs() if item.request_id == "req-2")
    assert stored_run.final_outcome == BehaviorOutcome.ENGAGED
    assert stored_run.score_delta == 2
    assert stored_run.effects_applied is True


@pytest.mark.parametrize(
    ("followup_scope", "followup_user_id"),
    [("session", 200), ("ambient", 300)],
)
@pytest.mark.asyncio
async def test_llm_history_detail_does_not_settle_same_second_feedback(
    pg_engine, monkeypatch, tmp_path, followup_scope: str, followup_user_id: int
) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=20,
        llm_session_group_window=20,
        llm_session_group_ambient_enabled=True,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")
    fixed_created_at = 1_700_000_000
    fixed_clock = SimpleNamespace(time=lambda: fixed_created_at)
    monkeypatch.setattr("pallas.product.llm.session_store_pg.time", fixed_clock)
    monkeypatch.setattr("pallas.product.llm.session_store.time", SimpleNamespace(time=lambda: fixed_created_at + 300))

    save_behavior_patterns([
        BehaviorPattern(
            pattern_id="p1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            success_score=7,
            applied_outcome_ids=["prior-request"],
        )
    ])
    await append_llm_message(10, 100, 200, "user", "跑题")
    await append_llm_message(10, 100, 200, "assistant", "少来。")
    append_behavior_run(
        BehaviorRun(
            request_id=f"req-same-second-{followup_scope}",
            bot_id=10,
            group_id=100,
            user_id=200,
            created_at=fixed_created_at,
            scene=BehaviorScene.PROVOCATION,
            user_text="跑题",
            reply_text="少来。",
            selected_pattern_ids=["p1"],
            selected_actions=[BehaviorAction.LIGHT_TEASE_AND_CLOSE],
        )
    )
    await append_llm_message(10, 100, followup_user_id, "user", "哈哈")

    group_turns = await list_group_ambient_messages(10, 100, limit=10)
    assert [(turn.user_id, turn.role, turn.content, turn.created_at) for turn in group_turns] == [
        (200, "user", "跑题", fixed_created_at),
        (200, "assistant", "少来。", fixed_created_at),
        (followup_user_id, "user", "哈哈", fixed_created_at),
    ]
    session_turns = await list_user_llm_messages(10, 100, 200, limit=10)
    if followup_scope == "session":
        assert [turn.content for turn in session_turns] == ["跑题", "少来。", "哈哈"]
    else:
        assert [turn.content for turn in session_turns] == ["跑题", "少来。"]
    assert all(turn.created_at == fixed_created_at for turn in session_turns)

    details = [await get_llm_history_session_detail(bot_id=10, group_id=100, user_id=200, limit=10) for _ in range(2)]
    assert all(detail is not None for detail in details)
    assert all(detail.behavior_runs[-1]["request_id"] == f"req-same-second-{followup_scope}" for detail in details)
    assert all(detail.behavior_runs[-1]["final_outcome"] is None for detail in details)
    assert all(detail.behavior_runs[-1]["score_delta"] == 0 for detail in details)

    stored_run = next(item for item in list_behavior_runs() if item.request_id == f"req-same-second-{followup_scope}")
    assert stored_run.final_outcome is None
    assert stored_run.score_delta == 0
    assert stored_run.effects_applied is False
    patterns = list_behavior_patterns()
    assert patterns == [
        BehaviorPattern(
            pattern_id="p1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            success_score=7,
            applied_outcome_ids=["prior-request"],
        )
    ]


@pytest.mark.asyncio
async def test_llm_history_detail_auto_settles_behavior_outcome_from_group_ambient_reply(
    pg_engine, monkeypatch, tmp_path
) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=20,
        llm_session_group_window=20,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    run_created_at = 1_700_000_000
    monkeypatch.setattr(
        "pallas.product.llm.session_store_pg.time",
        SimpleNamespace(time=lambda: run_created_at - 1),
    )
    await append_llm_message(10, 100, 200, "user", "你又来这套")
    monkeypatch.setattr(
        "pallas.product.llm.session_store_pg.time",
        SimpleNamespace(time=lambda: run_created_at),
    )
    await append_llm_message(10, 100, 200, "assistant", "少来。")
    turns = await list_user_llm_messages(10, 100, 200, limit=10)
    user_turn = next(item for item in turns if item.role == "user")
    assistant_turn = next(item for item in turns if item.role == "assistant")
    assert user_turn.created_at == run_created_at - 1
    assert assistant_turn.created_at == run_created_at
    save_behavior_patterns([
        BehaviorPattern(
            pattern_id="p1",
            scene=BehaviorScene.PROVOCATION,
            action=BehaviorAction.LIGHT_TEASE_AND_CLOSE,
            success_score=0,
        )
    ])
    append_behavior_run(
        BehaviorRun(
            request_id="req-ambient-1",
            bot_id=10,
            group_id=100,
            user_id=200,
            created_at=run_created_at,
            scene=BehaviorScene.PROVOCATION,
            reply_text="少来。",
            selected_pattern_ids=["p1"],
            selected_actions=[BehaviorAction.LIGHT_TEASE_AND_CLOSE],
        )
    )
    followup_created_at = run_created_at + 1
    monkeypatch.setattr(
        "pallas.product.llm.session_store_pg.time",
        SimpleNamespace(time=lambda: followup_created_at),
    )
    await append_llm_message(10, 100, 300, "user", "哈哈那然后呢？")
    followup_turn = (await list_user_llm_messages(10, 100, 300, limit=10))[-1]
    assert followup_turn.created_at == run_created_at + 1
    assert assistant_turn.created_at < followup_turn.created_at

    detail = await get_llm_history_session_detail(bot_id=10, group_id=100, user_id=200, limit=10)
    assert detail is not None
    assert detail.behavior_runs[-1]["request_id"] == "req-ambient-1"
    assert detail.behavior_runs[-1]["final_outcome"] == BehaviorOutcome.ENGAGED
    assert detail.behavior_runs[-1]["score_delta"] == 2
    assert list_behavior_patterns()[0].success_score == 2


@pytest.mark.asyncio
async def test_llm_history_detail_auto_settles_behavior_outcome_from_group_ambient_derailed(
    pg_engine, monkeypatch, tmp_path
) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    cfg = LlmConfig(
        llm_session_enabled=True,
        llm_session_user_window=20,
        llm_session_group_window=20,
        llm_session_user_ttl_sec=0,
    )
    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.core.foundation.db.runtime.get_db_backend", lambda: "postgresql")

    run_created_at = 1_700_000_000
    monkeypatch.setattr(
        "pallas.product.llm.session_store_pg.time",
        SimpleNamespace(time=lambda: run_created_at - 1),
    )
    await append_llm_message(10, 100, 200, "user", "在聊抽卡")
    monkeypatch.setattr(
        "pallas.product.llm.session_store_pg.time",
        SimpleNamespace(time=lambda: run_created_at),
    )
    await append_llm_message(10, 100, 200, "assistant", "突然去聊庆典。")
    turns = await list_user_llm_messages(10, 100, 200, limit=10)
    user_turn = next(item for item in turns if item.role == "user")
    assistant_turn = next(item for item in turns if item.role == "assistant")
    assert user_turn.created_at == run_created_at - 1
    assert assistant_turn.created_at == run_created_at
    save_behavior_patterns([
        BehaviorPattern(
            pattern_id="p2",
            scene=BehaviorScene.SMALLTALK,
            action=BehaviorAction.AVOID_FORCED_TOPIC_SHIFT,
            success_score=0,
        )
    ])
    append_behavior_run(
        BehaviorRun(
            request_id="req-ambient-2",
            bot_id=10,
            group_id=100,
            user_id=200,
            created_at=run_created_at,
            scene=BehaviorScene.SMALLTALK,
            reply_text="突然去聊庆典。",
            selected_pattern_ids=["p2"],
            selected_actions=[BehaviorAction.AVOID_FORCED_TOPIC_SHIFT],
        )
    )
    followup_created_at = run_created_at + 1
    monkeypatch.setattr(
        "pallas.product.llm.session_store_pg.time",
        SimpleNamespace(time=lambda: followup_created_at),
    )
    await append_llm_message(10, 100, 300, "user", "你别转话题啊，还在说抽卡")
    followup_turn = (await list_user_llm_messages(10, 100, 300, limit=10))[-1]
    assert followup_turn.created_at == run_created_at + 1
    assert assistant_turn.created_at < followup_turn.created_at

    detail = await get_llm_history_session_detail(bot_id=10, group_id=100, user_id=200, limit=10)
    assert detail is not None
    assert detail.behavior_runs[-1]["request_id"] == "req-ambient-2"
    assert detail.behavior_runs[-1]["final_outcome"] == BehaviorOutcome.DERAILED
    assert detail.behavior_runs[-1]["score_delta"] == -3
    assert list_behavior_patterns()[0].success_score == -3


def _pg_like_backend(data: list[LlmChatTurn]):
    """模拟 Pg 后端 list_user_messages：按旧→新升序、只返回最新 limit 条。"""

    class Backend:
        async def list_user_messages(self, bot_id, group_id, user_id, *, limit, ttl_sec):
            return list(data[-limit:])

    return Backend()


@pytest.mark.asyncio
async def test_list_user_llm_messages_returns_newest_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """读取窗口应取最新尾部而非最旧头部（后端按旧→新升序返回）。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_window=6)
    monkeypatch.setattr("pallas.product.llm.session_store.is_llm_session_store_available", lambda: True)
    data = [
        LlmChatTurn(role="user" if i % 2 == 0 else "assistant", content=f"t-{i}", user_id=200, created_at=i)
        for i in range(200)
    ]
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: _pg_like_backend(data))
    turns = await list_user_llm_messages(1, 100, 200, cfg=cfg)
    assert [turn.content for turn in turns] == [f"t-{i}" for i in range(194, 200)]


@pytest.mark.asyncio
async def test_list_user_llm_messages_explicit_limit_not_clamped_to_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """显式 limit 不应被可见窗口钳到 18，摘要/记忆/反馈需要读取更大的存储窗口。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_window=6)
    monkeypatch.setattr("pallas.product.llm.session_store.is_llm_session_store_available", lambda: True)
    data = [LlmChatTurn(role="user", content=f"t-{i}", user_id=200, created_at=i) for i in range(200)]
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: _pg_like_backend(data))
    turns = await list_user_llm_messages(1, 100, 200, limit=50, cfg=cfg)
    assert [turn.content for turn in turns] == [f"t-{i}" for i in range(150, 200)]


@pytest.mark.asyncio
async def test_read_user_llm_compaction_snapshot_passes_storage_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """压缩快照门面直接透传存储上限，不经过可见窗口裁剪。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_window=6)
    calls: dict[str, int] = {}

    class FakeBackend:
        async def read_user_compaction_snapshot(self, bot_id, group_id, user_id, *, limit, ttl_sec):
            calls["limit"] = limit
            calls["ttl_sec"] = ttl_sec
            return []

        async def list_user_messages(self, *_a, **_k):
            raise AssertionError("compaction snapshot must not use visible trimming")

    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.session_store.session_store_backend_ready", lambda: True)
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: FakeBackend())

    assert await read_user_llm_compaction_snapshot(1, 100, 200, limit=50, cfg=cfg) == []
    assert calls["limit"] == 50
    assert calls["ttl_sec"] >= 0


@pytest.mark.asyncio
async def test_list_user_llm_messages_preserves_summary_with_newest_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    """摘要应始终保留，其后接最新 (max_items-1) 条非摘要轮次（模型为压缩后紧邻窗口的态）。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_window=6)
    monkeypatch.setattr("pallas.product.llm.session_store.is_llm_session_store_available", lambda: True)
    data = [LlmChatTurn(role="user", content="【此前对话摘要】\n早期总结", user_id=200, created_at=0)]
    for i in range(1, 8):
        data.append(
            LlmChatTurn(role="user" if i % 2 == 0 else "assistant", content=f"t-{i}", user_id=200, created_at=i)
        )
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: _pg_like_backend(data))
    turns = await list_user_llm_messages(1, 100, 200, cfg=cfg)
    contents = [turn.content for turn in turns]
    assert contents[0].startswith("【此前对话摘要】")
    assert contents[1:] == [f"t-{i}" for i in range(3, 8)]
    assert len(turns) == 6


@pytest.mark.asyncio
async def test_list_user_llm_messages_does_not_hoist_ordinary_marker_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """普通消息仅含标记（无内部完整前缀）时不得被当作摘要置顶。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_window=4)
    monkeypatch.setattr("pallas.product.llm.session_store.is_llm_session_store_available", lambda: True)
    data = [
        LlmChatTurn(role="user", content="t-0", user_id=200, created_at=0),
        LlmChatTurn(role="user", content="【此前对话摘要】这是普通消息", user_id=200, created_at=1),
    ]
    for i in range(2, 6):
        data.append(LlmChatTurn(role="user", content=f"t-{i}", user_id=200, created_at=i))
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: _pg_like_backend(data))
    turns = await list_user_llm_messages(1, 100, 200, cfg=cfg)
    assert [turn.content for turn in turns] == [f"t-{i}" for i in range(2, 6)]


@pytest.mark.asyncio
async def test_list_user_llm_messages_limit_one_without_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """limit=1 无摘要：仍返回最新 1 条，不越界。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_window=6)
    monkeypatch.setattr("pallas.product.llm.session_store.is_llm_session_store_available", lambda: True)
    data = [
        LlmChatTurn(role="user", content="旧提问", user_id=200, created_at=0),
        LlmChatTurn(role="assistant", content="旧回复", user_id=200, created_at=1),
        LlmChatTurn(role="user", content="最新提问", user_id=200, created_at=2),
    ]
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: _pg_like_backend(data))
    turns = await list_user_llm_messages(1, 100, 200, limit=1, cfg=cfg)
    assert [turn.content for turn in turns] == ["最新提问"]


@pytest.mark.asyncio
async def test_list_user_llm_messages_limit_one_with_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """limit=1 且摘要存在：只返回摘要，不把剩余窗口兜底全部带出。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_window=6)
    monkeypatch.setattr("pallas.product.llm.session_store.is_llm_session_store_available", lambda: True)
    data = [
        LlmChatTurn(role="user", content="【此前对话摘要】\n早期总结", user_id=200, created_at=0),
        LlmChatTurn(role="user", content="最新提问", user_id=200, created_at=1),
        LlmChatTurn(role="assistant", content="最新回复", user_id=200, created_at=2),
    ]
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: _pg_like_backend(data))
    turns = await list_user_llm_messages(1, 100, 200, limit=1, cfg=cfg)
    assert len(turns) == 1
    assert turns[0].content.startswith("【此前对话摘要】")


@pytest.mark.asyncio
async def test_list_user_llm_messages_keeps_latest_user_and_assistant_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    """窗口裁剪应保留最新 user 与 assistant 尾部，而非最旧头部。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_user_window=4)
    monkeypatch.setattr("pallas.product.llm.session_store.is_llm_session_store_available", lambda: True)
    data = [
        LlmChatTurn(role="user", content="u-0", user_id=200, created_at=0),
        LlmChatTurn(role="assistant", content="a-1", user_id=200, created_at=1),
        LlmChatTurn(role="user", content="u-2", user_id=200, created_at=2),
        LlmChatTurn(role="assistant", content="a-3", user_id=200, created_at=3),
        LlmChatTurn(role="user", content="u-4", user_id=200, created_at=4),
        LlmChatTurn(role="assistant", content="a-5", user_id=200, created_at=5),
    ]
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: _pg_like_backend(data))
    turns = await list_user_llm_messages(1, 100, 200, cfg=cfg)
    assert [turn.content for turn in turns] == ["u-2", "a-3", "u-4", "a-5"]
    assert turns[-1].role == "assistant"
    assert turns[-2].role == "user"


@pytest.mark.asyncio
async def test_list_user_llm_messages_default_visible_window_not_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认可见窗口 18 不应被放大；后端只请求 20（18+2 摘要缓冲）。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True)  # llm_session_user_window 默认 18
    monkeypatch.setattr("pallas.product.llm.session_store.is_llm_session_store_available", lambda: True)
    data = [LlmChatTurn(role="user", content=f"t-{i}", user_id=200, created_at=i) for i in range(60)]
    requested: dict[str, int] = {}

    class Backend:
        async def list_user_messages(self, bot_id, group_id, user_id, *, limit, ttl_sec):
            requested["limit"] = limit
            return list(data[-limit:])

    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: Backend())
    turns = await list_user_llm_messages(1, 100, 200, cfg=cfg)
    assert requested["limit"] == 20
    assert len(turns) == 18
    assert [turn.content for turn in turns] == [f"t-{i}" for i in range(42, 60)]


@pytest.mark.asyncio
async def test_compact_with_source_ids_requires_non_empty_ids_and_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(llm_session_enabled=True)
    calls = 0

    class FakeBackend:
        async def compact_user_with_summary(self, *_a, **_k):
            nonlocal calls
            calls += 1
            return True

    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.session_store.session_store_backend_ready", lambda: True)
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: FakeBackend())

    assert not await compact_user_llm_history_with_summary(
        1, 100, 200, "summary", keep_messages=2, source_message_ids=[], summary_created_at=1
    )
    assert not await compact_user_llm_history_with_summary(
        1, 100, 200, "summary", keep_messages=2, source_message_ids=["1"], summary_created_at=None
    )
    assert not await compact_user_llm_history_with_summary(
        1,
        100,
        200,
        "summary",
        keep_messages=2,
        source_message_ids=["1"],
        summary_created_at="bad",  # type: ignore[arg-type]
    )
    assert calls == 0


@pytest.mark.asyncio
async def test_compact_rejects_summary_prefix_broken_by_vision_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CQ 图片摘要经 vision 清理后前缀被移到 [图片] 之后，门面应拒绝且不调 backend。"""
    clear_llm_config_cache()
    cfg = LlmConfig(llm_session_enabled=True, llm_session_strip_vision_enabled=True)
    calls = 0

    class FakeBackend:
        async def compact_user_with_summary(self, *_a, **_k):
            nonlocal calls
            calls += 1
            return True

    monkeypatch.setattr("pallas.product.llm.session_store.get_llm_config", lambda: cfg)
    monkeypatch.setattr("pallas.product.llm.session_store.session_store_backend_ready", lambda: True)
    monkeypatch.setattr("pallas.product.llm.session_store.resolve_session_backend", lambda: FakeBackend())

    assert not await compact_user_llm_history_with_summary(
        1,
        100,
        200,
        "[CQ:image,url=https://example.com/a.png] 讨论了猫",
        keep_messages=2,
        source_message_ids=["1"],
        summary_created_at=1,
        cfg=cfg,
    )
    assert calls == 0

    assert await compact_user_llm_history_with_summary(
        1,
        100,
        200,
        "讨论了猫",
        keep_messages=2,
        source_message_ids=["1"],
        summary_created_at=1,
        cfg=cfg,
    )
    assert calls == 1
