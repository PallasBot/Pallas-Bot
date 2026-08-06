from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.assembler.context import assemble_direct_chat_context, assemble_repeater_context
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.knowledge.models import KnowledgeInjectionResult
from pallas.product.llm.memory.inject import MemoryInjectionResult


@pytest.mark.asyncio
async def test_assemble_repeater_context_delegates_to_persona_builder(monkeypatch) -> None:
    async def build_context(*args, **kwargs):
        assert args == (1, 2, "测试")
        assert kwargs == {"purpose": "select"}
        return {"system_prompt": "persona"}

    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.build_repeater_llm_persona_context",
        build_context,
    )

    assert await assemble_repeater_context(1, 2, "测试", purpose="select") == {"system_prompt": "persona"}


@pytest.mark.asyncio
async def test_direct_chat_context_appends_repeater_expression_reference(monkeypatch) -> None:
    memory = AsyncMock(return_value=MemoryInjectionResult(system_prompt="memory", trace={"hit_count": 0}))
    knowledge = AsyncMock(return_value=KnowledgeInjectionResult(system_prompt="knowledge", trace={"hit_count": 0}))
    expressions = AsyncMock(return_value=("【表达习惯参考】\n- 顺手短句更自然。", [object()]))

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
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.build_expression_context_with_entries",
        expressions,
    )
    monkeypatch.setattr("pallas.product.llm.knowledge.embedding_client.embedding_capability_trace", lambda _cfg: {})
    monkeypatch.setattr("pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode", lambda _cfg: "hybrid")

    result = await assemble_direct_chat_context(
        "base",
        bot_id=1,
        group_id=2,
        user_id=3,
        query_text="牛牛出来",
        cfg=LlmConfig(llm_chat_enabled=True),
        allow_persistent_memory=False,
    )

    assert result.system_prompt.endswith("【表达习惯参考】\n- 顺手短句更自然。")
    assert "expression" in result.stage_durations_ms
    expressions.assert_awaited_once_with(2, "牛牛出来", bot_id=1, scene="group_chat")


@pytest.mark.asyncio
async def test_direct_chat_context_skips_expression_reference_when_style_profile_exists(monkeypatch) -> None:
    memory = AsyncMock(return_value=MemoryInjectionResult(system_prompt="memory", trace={"hit_count": 0}))
    knowledge = AsyncMock(return_value=KnowledgeInjectionResult(system_prompt="knowledge", trace={"hit_count": 0}))
    expressions = AsyncMock()

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
    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.build_expression_context_with_entries",
        expressions,
    )
    monkeypatch.setattr("pallas.product.llm.knowledge.embedding_client.embedding_capability_trace", lambda _cfg: {})
    monkeypatch.setattr("pallas.product.llm.knowledge.vector_backend.vector_retrieve_mode", lambda _cfg: "hybrid")

    result = await assemble_direct_chat_context(
        "base",
        bot_id=1,
        group_id=2,
        user_id=3,
        query_text="牛牛出来",
        cfg=LlmConfig(llm_chat_enabled=True),
        allow_persistent_memory=False,
        allow_expression_reference=False,
    )

    assert result.system_prompt == "knowledge"
    assert result.stage_durations_ms["expression"] == 0
    expressions.assert_not_awaited()
