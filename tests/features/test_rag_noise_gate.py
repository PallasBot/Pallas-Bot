from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.inject import looks_like_knowledge_query
from pallas.product.llm.knowledge.models import KnowledgeRetrievalMode, KnowledgeSourceDecl, RetrievedKnowledgeChunk
from pallas.product.llm.knowledge.registry import retrieve_from_knowledge_sources
from pallas.product.llm.memory.inject import enrich_system_with_memory_context
from pallas.product.llm.session_store import LlmChatTurn


def test_looks_like_knowledge_query_gate() -> None:
    assert looks_like_knowledge_query("怎么清空聊天记录")
    assert looks_like_knowledge_query("如何打开群记忆")
    assert not looks_like_knowledge_query("谁问你了")
    assert not looks_like_knowledge_query("点牛牛")
    assert not looks_like_knowledge_query("抓")


@pytest.mark.asyncio
async def test_memory_inject_does_not_pad_ambient_when_persistent_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_memory_rag_enabled=True, llm_memory_rag_min_score=10)
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.can_read_persistent_memory",
        lambda _cfg=None: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.retrieve_memory_hits",
        AsyncMock(return_value=[{"content": "你把漂亮牛牛揪出来", "score": 68, "source": "auto_episode"}]),
    )
    ambient_mock = AsyncMock(
        return_value=[
            LlmChatTurn(role="user", user_id=1, content="画画次数", created_at=1),
            LlmChatTurn(role="user", user_id=1, content="古风小生", created_at=2),
        ]
    )
    monkeypatch.setattr("pallas.product.llm.memory.inject.list_group_ambient_messages", ambient_mock)
    result = await enrich_system_with_memory_context("base", bot_id=1, group_id=2, query_text="漂亮牛牛", cfg=cfg)
    assert result.trace["hit_count"] == 1
    assert "漂亮牛牛" in result.system_prompt
    ambient_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_inject_ambient_only_when_empty_and_above_min_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_memory_rag_enabled=True,
        llm_memory_rag_min_score=20,
        llm_memory_rag_top_k=3,
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.can_read_persistent_memory",
        lambda _cfg=None: True,
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.retrieve_memory_hits",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.list_group_ambient_messages",
        AsyncMock(
            return_value=[
                LlmChatTurn(role="user", user_id=1, content="我把漂亮牛牛吃掉了", created_at=1),
                LlmChatTurn(role="user", user_id=1, content="画画次数", created_at=2),
            ]
        ),
    )
    result = await enrich_system_with_memory_context(
        "base",
        bot_id=1,
        group_id=2,
        query_text="漂亮牛牛",
        cfg=cfg,
    )
    assert result.trace["hit_count"] >= 1
    assert all("画画" not in str(item.get("content") or "") for item in result.trace["entries"])


def test_knowledge_retrieve_filters_below_min_score(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_knowledge_sources_enabled=True, llm_knowledge_min_score=40)

    def fake_retrieve(decl, query_text, *, top_k, max_chunk_len):
        return [
            RetrievedKnowledgeChunk(source_id=decl.source_id, title="弱", content="无关", score=12),
            RetrievedKnowledgeChunk(source_id=decl.source_id, title="强", content="相关", score=55),
        ]

    from pallas.product.llm.knowledge import registry as reg

    class FakeRow:
        source_id = "demo.faq"
        decl = KnowledgeSourceDecl(
            source_id="demo.faq",
            title="demo",
            chunks=[{"title": "x", "content": "y", "keywords": "z"}],
            retrieval_mode=KnowledgeRetrievalMode.PROMPT_INJECT,
            top_k=3,
            max_chunk_len=400,
        )

    monkeypatch.setattr(reg, "list_active_knowledge_sources", lambda *, cfg=None: [FakeRow()])
    monkeypatch.setattr(reg, "retrieve_chunks_from_decl", fake_retrieve)
    monkeypatch.setattr(reg, "can_read_generic_knowledge", lambda _cfg=None: True)

    hits = retrieve_from_knowledge_sources("随便问问", bot_id=1, group_id=2, user_id=3, cfg=cfg)
    assert len(hits) == 1
    assert hits[0].title == "强"
