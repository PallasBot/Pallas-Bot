from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.assembler.context import assemble_direct_chat_context
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.inject import looks_like_knowledge_query
from pallas.product.llm.knowledge.models import (
    KnowledgeInjectionResult,
    KnowledgeRetrievalMode,
    KnowledgeSourceDecl,
    RetrievedKnowledgeChunk,
)
from pallas.product.llm.knowledge.registry import retrieve_from_knowledge_sources
from pallas.product.llm.memory.inject import (
    MemoryInjectionResult,
    PersonFactsInjectionResult,
    RelationshipInjectionResult,
    enrich_system_with_memory_context,
)
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
async def test_memory_inject_skips_auto_episode_that_echoes_current_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_memory_rag_enabled=True, llm_memory_rag_min_score=10)
    monkeypatch.setattr("pallas.product.llm.memory.inject.can_read_persistent_memory", lambda _cfg=None: True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.retrieve_memory_hits",
        AsyncMock(return_value=[{"content": "我又改需求了，烦", "score": 68, "source": "auto_episode"}]),
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.list_group_ambient_messages",
        AsyncMock(return_value=[LlmChatTurn(role="user", user_id=1, content="我又改需求了，烦", created_at=1)]),
    )

    result = await enrich_system_with_memory_context(
        "base",
        bot_id=1,
        group_id=2,
        query_text="我又改需求了，烦",
        cfg=cfg,
    )

    assert result.trace["hit_count"] == 0
    assert result.trace["skipped_current_turn_echoes"] == 2
    assert "相关群内旧事" not in result.system_prompt


@pytest.mark.asyncio
async def test_memory_inject_skips_retrieval_when_current_turn_disables_persistent_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_memory_rag_enabled=True, llm_memory_rag_min_score=10)
    retrieve_mock = AsyncMock(
        return_value=[{"content": "我又改输出了，烦", "score": 68, "source": "auto_episode"}],
    )
    monkeypatch.setattr("pallas.product.llm.memory.inject.retrieve_memory_hits", retrieve_mock)
    ambient_mock = AsyncMock(return_value=[])
    monkeypatch.setattr("pallas.product.llm.memory.inject.list_group_ambient_messages", ambient_mock)

    result = await enrich_system_with_memory_context(
        "base",
        bot_id=1,
        group_id=2,
        query_text="我又改输出了，烦",
        cfg=cfg,
        allow_persistent_memory=False,
    )

    retrieve_mock.assert_not_awaited()
    ambient_mock.assert_not_awaited()
    assert result.system_prompt == "base"
    assert result.trace == {
        "hit_count": 0,
        "sources": [],
        "entries": [],
        "skipped_short_social_turn": True,
    }


@pytest.mark.asyncio
async def test_memory_inject_still_retrieves_when_current_turn_allows_persistent_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_memory_rag_enabled=True, llm_memory_rag_min_score=10)
    retrieve_mock = AsyncMock(
        return_value=[{"content": "上次把输出改成短句", "score": 68, "source": "auto_episode"}],
    )
    monkeypatch.setattr("pallas.product.llm.memory.inject.can_read_persistent_memory", lambda _cfg=None: True)
    monkeypatch.setattr("pallas.product.llm.memory.inject.retrieve_memory_hits", retrieve_mock)

    result = await enrich_system_with_memory_context(
        "base",
        bot_id=1,
        group_id=2,
        query_text="刚才那个输出怎么改的？",
        cfg=cfg,
        allow_persistent_memory=True,
    )

    retrieve_mock.assert_awaited_once()
    assert result.trace["hit_count"] == 1
    assert "上次把输出改成短句" in result.system_prompt


@pytest.mark.asyncio
async def test_direct_chat_short_social_skips_relationship_and_person_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory_mock = AsyncMock(return_value=MemoryInjectionResult(system_prompt="memory", trace={"hit_count": 0}))
    knowledge_mock = AsyncMock(return_value=KnowledgeInjectionResult(system_prompt="knowledge", trace={"hit_count": 0}))
    relationship_mock = AsyncMock(
        return_value=RelationshipInjectionResult(system_prompt="relationship", trace={"hit_count": 1})
    )
    person_facts_mock = AsyncMock(
        return_value=PersonFactsInjectionResult(system_prompt="person facts", trace={"hit_count": 1})
    )
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_memory_context", memory_mock)
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_knowledge_sources", knowledge_mock)
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_relationship_context",
        relationship_mock,
    )
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_person_facts", person_facts_mock)
    monkeypatch.setattr("pallas.product.llm.knowledge.embedding_client.embedding_capability_trace", lambda _cfg: {})
    monkeypatch.setattr("pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode", lambda _cfg: "hybrid")

    result = await assemble_direct_chat_context(
        "base",
        bot_id=1,
        group_id=2,
        user_id=3,
        query_text="这也能改？",
        cfg=LlmConfig(llm_chat_enabled=True),
        allow_persistent_memory=False,
    )

    relationship_mock.assert_not_awaited()
    person_facts_mock.assert_not_awaited()
    assert result.system_prompt == "knowledge"
    assert result.relationship_trace == {"hit_count": 0, "sources": [], "skipped_short_social_turn": True}


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
