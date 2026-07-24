from __future__ import annotations

import pytest

from pallas.product.llm.memory.mid_term import MID_TERM_PREFIX, list_mid_term_summaries
from pallas.product.llm.ops_config import (
    LlmMemoryOpsConfig,
    LlmSessionOpsConfig,
    memory_ops_patch_dict,
    session_ops_patch_dict,
)
from pallas.product.llm.session_models import LlmChatTurn, LlmHistorySessionSummary


@pytest.mark.asyncio
async def test_list_mid_term_summaries_extracts_prefix(monkeypatch) -> None:
    async def fake_sessions(*, bot_id=None, group_id=None, user_id=None, limit=50):
        return [
            LlmHistorySessionSummary(
                session_key="1:0:9",
                bot_id=1,
                group_id=0,
                user_id=9,
                turn_count=2,
                first_created_at=1,
                last_created_at=2,
                last_role="user",
                last_content="hi",
            )
        ]

    async def fake_messages(bot_id, group_id, user_id, *, limit=None, cfg=None):
        return [
            LlmChatTurn(role="user", content=f"{MID_TERM_PREFIX}\n昨天聊了猫", user_id=9, created_at=1),
            LlmChatTurn(role="user", content="普通消息", user_id=9, created_at=2),
        ]

    monkeypatch.setattr("pallas.product.llm.memory.mid_term.list_llm_history_sessions", fake_sessions)
    monkeypatch.setattr("pallas.product.llm.memory.mid_term.list_user_llm_messages", fake_messages)

    items = await list_mid_term_summaries(bot_id=1, limit=10)
    assert len(items) == 1
    assert items[0]["summary"] == "昨天聊了猫"


def test_ops_config_patch_dicts_keep_known_fields() -> None:
    session_patch = session_ops_patch_dict({"llm_session_user_window": 24, "unknown": 1})
    assert session_patch["llm_session_user_window"] == 24
    assert "unknown" not in session_patch
    assert LlmSessionOpsConfig.model_validate(session_patch)

    memory_patch = memory_ops_patch_dict({"llm_memory_rag_top_k": 4})
    assert memory_patch["llm_memory_rag_top_k"] == 4
    assert LlmMemoryOpsConfig.model_validate(memory_patch)
