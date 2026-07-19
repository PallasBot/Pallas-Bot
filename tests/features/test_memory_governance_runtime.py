from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.kernel.observability import build_conversation_kernel_status
from pallas.product.llm.memory.inject import (
    append_memory_context,
    append_relationship_context,
    enrich_system_with_memory_context,
    enrich_system_with_relationship_context,
)


@pytest.mark.asyncio
async def test_append_memory_context_skips_when_policy_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_memory_rag_enabled=True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.can_read_persistent_memory",
        lambda _cfg=None: False,
    )
    result = await append_memory_context("base", bot_id=1, group_id=2, query_text="银灰", cfg=cfg)
    assert result == "base"


@pytest.mark.asyncio
async def test_append_relationship_context_skips_when_policy_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_relationship_notes_enabled=True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.can_read_persistent_memory",
        lambda _cfg=None: False,
    )
    result = await append_relationship_context(
        "base",
        bot_id=1,
        group_id=2,
        user_id=3,
        cfg=cfg,
    )
    assert result == "base"


@pytest.mark.asyncio
async def test_enrich_memory_context_returns_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_memory_rag_enabled=True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.can_read_persistent_memory",
        lambda _cfg=None: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.retrieve_memory_hits",
        AsyncMock(return_value=[{"content": "银灰是我推", "score": 5, "source": "episode_note"}]),
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.list_group_ambient_messages",
        AsyncMock(return_value=[]),
    )
    result = await enrich_system_with_memory_context("base", bot_id=1, group_id=2, query_text="银灰", cfg=cfg)
    assert "相关群内旧事" in result.system_prompt
    assert result.trace["hit_count"] == 1
    assert result.trace["sources"] == ["episode_note"]


@pytest.mark.asyncio
async def test_enrich_relationship_context_returns_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_relationship_notes_enabled=True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.can_read_persistent_memory",
        lambda _cfg=None: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.retrieve_relationship_note",
        AsyncMock(return_value="这个人喜欢嘴硬"),
    )
    result = await enrich_system_with_relationship_context("base", bot_id=1, group_id=2, user_id=3, cfg=cfg)
    assert "关系备注" in result.system_prompt
    assert result.trace["hit_count"] == 1
    assert result.trace["sources"] == ["relationship_note"]


def test_build_conversation_kernel_status_exposes_summary_gate() -> None:
    status = build_conversation_kernel_status(
        LlmConfig(
            llm_chat_enabled=True,
            llm_session_enabled=True,
            llm_session_summary_enabled=True,
            llm_memory_rag_enabled=True,
        )
    )
    assert status["runtime_state_summary_active"] is True
    policy = status["memory_policy"]
    assert policy["read_session"] is True
    assert policy["write_session"] is True
    assert policy["runtime_state_summary_enabled"] is True
    assert policy["read_persistent_memory"] is True
