from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.memory.inject import enrich_system_with_relationship_context
from pallas.product.llm.memory.relationship_store import RelationshipProfile


@pytest.mark.asyncio
async def test_relationship_inject_fallback_when_empty() -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_relationship_notes_enabled=True)
    with patch(
        "pallas.product.llm.memory.inject.retrieve_relationship_profile",
        new=AsyncMock(return_value=None),
    ):
        result = await enrich_system_with_relationship_context(
            "base",
            bot_id=1,
            group_id=2,
            user_id=3,
            cfg=cfg,
        )
    assert "打过照面的群友" in result.system_prompt
    assert result.trace["fallback"] is True
    assert result.trace["hit_count"] == 0


@pytest.mark.asyncio
async def test_relationship_inject_facts_and_deltas() -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_relationship_notes_enabled=True)
    profile = RelationshipProfile(
        content="是本群群主；希望被叫作队长",
        warmth_delta=0.06,
        assertiveness_delta=-0.03,
        source="observe",
    )
    with patch(
        "pallas.product.llm.memory.inject.retrieve_relationship_profile",
        new=AsyncMock(return_value=profile),
    ):
        result = await enrich_system_with_relationship_context(
            "base",
            bot_id=1,
            group_id=2,
            user_id=3,
            cfg=cfg,
        )
    assert "是本群群主" in result.system_prompt
    assert "希望被叫作队长" in result.system_prompt
    assert "称呼对方时优先用「队长」" in result.system_prompt
    assert "不得覆盖" in result.system_prompt
    assert result.trace["hit_count"] == 1
    assert result.trace["note_source"] == "observe"
    assert result.trace["preferred_name"] == "队长"
    assert result.trace["warmth_delta"] == 0.06
    assert result.trace["assertiveness_delta"] == -0.03
