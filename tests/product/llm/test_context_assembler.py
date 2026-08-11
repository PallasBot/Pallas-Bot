from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.assembler.context import assemble_direct_chat_context
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.models import KnowledgeInjectionResult
from pallas.product.llm.memory.inject import MemoryInjectionResult


def test_assembler_package_omits_retired_repeater_context() -> None:
    import pallas.product.llm.assembler as assembler

    assert not hasattr(assembler, "assemble_repeater_context")


@pytest.mark.asyncio
async def test_direct_chat_context_returns_retrieval_blocks_without_expression_append(monkeypatch) -> None:
    memory = AsyncMock(return_value=MemoryInjectionResult(system_prompt="memory", trace={"hit_count": 0}))
    knowledge = AsyncMock(return_value=KnowledgeInjectionResult(system_prompt="knowledge", trace={"hit_count": 0}))
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_memory_context", memory)
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_knowledge_sources", knowledge)
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_relationship_context",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_person_facts",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("pallas.product.llm.knowledge.embedding_client.embedding_capability_trace", lambda _cfg: {})
    monkeypatch.setattr("pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode", lambda _cfg: "hybrid")

    result = await assemble_direct_chat_context(
        bot_id=1,
        group_id=2,
        user_id=3,
        query_text="牛牛出来",
        cfg=LlmConfig(llm_chat_enabled=True),
        allow_persistent_memory=False,
    )

    assert result.memory == "memory"
    assert result.knowledge == "knowledge"
    assert result.relationship == ""
    assert result.person_facts == ""
    assert "expression" not in result.stage_durations_ms


@pytest.mark.asyncio
async def test_direct_chat_context_keeps_retrieval_blocks_separate(monkeypatch) -> None:
    memory = AsyncMock(return_value=MemoryInjectionResult(system_prompt="memory", trace={"hit_count": 0}))
    knowledge = AsyncMock(return_value=KnowledgeInjectionResult(system_prompt="knowledge", trace={"hit_count": 0}))
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_memory_context", memory)
    monkeypatch.setattr("pallas.product.llm.assembler.context.enrich_system_with_knowledge_sources", knowledge)
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_relationship_context",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.enrich_system_with_person_facts",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("pallas.product.llm.knowledge.embedding_client.embedding_capability_trace", lambda _cfg: {})
    monkeypatch.setattr("pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode", lambda _cfg: "hybrid")

    result = await assemble_direct_chat_context(
        bot_id=1,
        group_id=2,
        user_id=3,
        query_text="牛牛出来",
        cfg=LlmConfig(llm_chat_enabled=True),
        allow_persistent_memory=False,
    )

    assert result.memory == "memory"
    assert result.knowledge == "knowledge"
    assert "expression" not in result.stage_durations_ms
