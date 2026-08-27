from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.session_models import LlmChatTurn
from pallas.product.llm.session_summary import (
    _summary_messages,
    clear_session_summary_state_for_tests,
    maybe_compact_session_history,
)


@pytest.mark.asyncio
async def test_summary_messages_excludes_existing_summary() -> None:
    turns = [
        LlmChatTurn(role="user", content="你好啊", user_id=1, created_at=1),
        LlmChatTurn(role="assistant", content="早呀", user_id=2, created_at=2),
        LlmChatTurn(role="user", content="【此前对话摘要】旧内容", user_id=1, created_at=0),
    ]
    out = await _summary_messages(turns)
    assert "旧内容" not in out
    assert "你好啊" in out
    assert "早呀" in out


@pytest.mark.asyncio
async def test_maybe_compact_skips_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_session_summary_state_for_tests()

    async def fake_list(*_a, **_k):
        return [LlmChatTurn(role="user", content="短对话", user_id=1, created_at=i) for i in range(10)]

    monkeypatch.setattr(
        "pallas.product.llm.session_summary.is_llm_session_store_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.session_summary.list_user_llm_messages",
        fake_list,
    )
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_session_enabled=True,
        llm_session_summary_enabled=True,
        llm_session_summary_threshold=40,
        llm_session_summary_cooldown_sec=0,
        llm_session_user_storage_window=200,
    )
    assert await maybe_compact_session_history(bot_id=1, group_id=2, user_id=3, cfg=cfg) is False


@pytest.mark.asyncio
async def test_maybe_compact_generates_and_saves_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_session_summary_state_for_tests()
    saved = {}

    async def fake_list(*_a, **_k):
        return [LlmChatTurn(role="user", content=f"讨论第{i}件事", user_id=1, created_at=i) for i in range(50)]

    async def fake_complete(*_a, **_k):
        return {"content": "群友讨论了多件事，约定周五继续"}

    async def fake_compact(*_a, **_k):
        saved["called"] = True
        return True

    monkeypatch.setattr(
        "pallas.product.llm.session_summary.is_llm_session_store_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.session_summary.list_user_llm_messages",
        fake_list,
    )
    monkeypatch.setattr(
        "pallas.product.llm.session_summary.complete_chat_message",
        fake_complete,
    )
    monkeypatch.setattr(
        "pallas.product.llm.session_summary.compact_user_llm_history_with_summary",
        fake_compact,
    )
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_session_enabled=True,
        llm_session_summary_enabled=True,
        llm_session_summary_threshold=40,
        llm_session_summary_keep_messages=16,
        llm_session_summary_cooldown_sec=0,
        llm_session_user_storage_window=200,
        llm_session_user_window=18,
    )
    assert await maybe_compact_session_history(bot_id=1, group_id=2, user_id=3, cfg=cfg) is True
    assert saved.get("called") is True
