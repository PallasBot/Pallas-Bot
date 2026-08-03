import pytest

from pallas.product.llm.memory.inject import enrich_system_with_memory_context
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
