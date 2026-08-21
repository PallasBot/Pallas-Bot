from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.injection_feedback import apply_negative_outcome
from pallas.product.llm.memory.inject import enrich_system_with_memory_context, rank_memory_hits_by_feedback
from pallas.product.llm.memory.planner import plan_memory_retrieval
from pallas.product.llm.memory.retrieve import filter_memory_candidates_for_scope, rank_memory_candidates
from pallas.product.llm.memory.store import derive_memory_metadata


def test_short_social_turn_skips_persistent_memory() -> None:
    assert plan_memory_retrieval("在吗").need_persistent is False
    assert plan_memory_retrieval("你还记得上次那个梗吗").need_persistent is True
    assert plan_memory_retrieval("漂亮牛牛").need_persistent is True


def test_memory_ranking_prefers_recent_important_same_scope_candidate() -> None:
    ranked = rank_memory_candidates(
        "上次那个梗",
        [
            {"content": "上次那个梗", "keywords": "上次,梗", "importance": 0.1, "created_at": 1},
            {"content": "上次那个梗", "keywords": "上次,梗", "importance": 0.9, "created_at": 2},
        ],
    )

    assert ranked[0]["importance"] == 0.9


def test_memory_scope_filter_rejects_expired_and_private_cross_group_candidates() -> None:
    candidates = [
        {"id": 1, "bot_id": 7, "group_id": 3, "visibility": "group", "expires_at": 0},
        {"id": 2, "bot_id": 7, "group_id": 0, "visibility": "private", "expires_at": 0},
        {"id": 3, "bot_id": 7, "group_id": 0, "visibility": "bot_global", "expires_at": 0},
        {"id": 4, "bot_id": 7, "group_id": 3, "visibility": "group", "expires_at": 99},
        {"id": 5, "bot_id": 8, "group_id": 3, "visibility": "group", "expires_at": 0},
    ]

    filtered = filter_memory_candidates_for_scope(candidates, bot_id=7, group_id=3, now=100)

    assert [item["id"] for item in filtered] == [1, 3]


def test_memory_metadata_uses_conservative_scope_and_source_defaults() -> None:
    group = derive_memory_metadata(group_id=3, source="teach")
    private = derive_memory_metadata(group_id=None, source="auto_episode")

    assert group == {
        "importance": 0.8,
        "confidence": 0.9,
        "expires_at": 0,
        "visibility": "group",
    }
    assert private == {
        "importance": 0.3,
        "confidence": 0.4,
        "expires_at": 0,
        "visibility": "private",
    }


@pytest.mark.asyncio
async def test_short_social_turn_does_not_query_persistent_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fake_retrieve(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("pallas.product.llm.memory.inject.retrieve_memory_hits", fake_retrieve)

    result = await enrich_system_with_memory_context(
        "base",
        bot_id=1,
        group_id=2,
        query_text="在吗",
    )

    assert called is False
    assert result.trace["skipped_unneeded_turn"] is True


@pytest.mark.asyncio
async def test_negative_memory_score_reorders_and_excludes_hits(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("pallas.product.llm.injection_feedback.time.time", lambda: 100)
    cfg = LlmConfig(llm_chat_enabled=True, llm_memory_rag_enabled=True)
    monkeypatch.setattr("pallas.product.llm.memory.inject.can_read_persistent_memory", lambda _cfg: True)
    monkeypatch.setattr(
        "pallas.product.llm.memory.inject.retrieve_memory_hits",
        AsyncMock(
            return_value=[
                {"id": 1, "content": "原本第一", "score": 10, "source": "teach"},
                {"id": 2, "content": "原本第二", "score": 9, "source": "teach"},
                {"id": 3, "content": "应被移除", "score": 8, "source": "teach"},
            ]
        ),
    )
    for index in range(2):
        apply_negative_outcome(
            outcome_id=f"memory-penalty-{index}",
            bot_id=1,
            group_id=2,
            reply_text="不合适",
            injection_snapshot={"memory_entries": [{"entry_id": "memory:1", "text_preview": "原本第一"}]},
            now=100,
        )
    for index in range(3):
        apply_negative_outcome(
            outcome_id=f"memory-exclude-{index}",
            bot_id=1,
            group_id=2,
            reply_text="不合适",
            injection_snapshot={"memory_entries": [{"entry_id": "memory:3", "text_preview": "应被移除"}]},
            now=100,
        )

    result = await enrich_system_with_memory_context(
        "base",
        bot_id=1,
        group_id=2,
        query_text="你还记得那件事吗",
        cfg=cfg,
    )

    assert result.system_prompt.index("原本第二") < result.system_prompt.index("原本第一")
    assert "应被移除" not in result.system_prompt


def test_memory_feedback_empty_ledger_preserves_hit_order(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    hits = [
        {"id": 2, "content": "first", "score": 9, "source": "teach"},
        {"id": 1, "content": "second", "score": 10, "source": "teach"},
    ]

    ranked = rank_memory_hits_by_feedback(hits, bot_id=1, group_id=2)

    assert ranked == hits
