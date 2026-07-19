from __future__ import annotations

import pytest

from pallas.product.persona.auto import derive_persona_from_bot_id
from pallas.product.persona.compile_persona_prompt import compile_persona_prompt


@pytest.mark.asyncio
async def test_build_drunk_chat_system_prompt_applies_drunk_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.drunk_chat_context import build_drunk_chat_system_prompt
    from pallas.product.llm.knowledge.models import KnowledgeInjectionResult
    from pallas.product.llm.memory.inject import MemoryInjectionResult, RelationshipInjectionResult

    async def fake_build_persona_llm_context(bot_id, group_id, user_text, **kwargs):
        bundle = compile_persona_prompt(
            derive_persona_from_bot_id(bot_id),
            None,
            bot_id=bot_id,
            group_id=group_id,
            base_system="基础牛格",
            mode=kwargs.get("mode", "normal"),
        )
        return bundle, None, 96

    async def noop_memory(system_prompt, **kwargs):
        return MemoryInjectionResult(system_prompt=system_prompt, trace={"hit_count": 0})

    async def noop_knowledge(system_prompt, **kwargs):
        return KnowledgeInjectionResult(system_prompt=system_prompt, trace={"hit_count": 0})

    async def noop_relationship(system_prompt, **kwargs):
        return RelationshipInjectionResult(system_prompt=system_prompt, trace={"hit_count": 0})

    monkeypatch.setattr(
        "pallas.product.llm.drunk_chat_context.build_persona_llm_context",
        fake_build_persona_llm_context,
    )
    monkeypatch.setattr("pallas.product.llm.drunk_chat_context.enrich_system_with_memory_context", noop_memory)
    monkeypatch.setattr("pallas.product.llm.drunk_chat_context.enrich_system_with_knowledge_sources", noop_knowledge)
    monkeypatch.setattr(
        "pallas.product.llm.drunk_chat_context.enrich_system_with_relationship_context",
        noop_relationship,
    )

    async def noop_expression(_group_id):
        return ""

    monkeypatch.setattr("pallas.product.llm.drunk_chat_context.build_group_expression_suffix", noop_expression)

    ctx = await build_drunk_chat_system_prompt(10001, 626266902, "你好呀")
    assert ctx is not None
    assert "基础牛格" in ctx.system_prompt
    assert "【醉酒状态】" in ctx.system_prompt
    assert ctx.temperature is None
    assert ctx.token_count == 96
