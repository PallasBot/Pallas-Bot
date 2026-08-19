from __future__ import annotations

import pytest

from pallas.product.llm.memory.mid_term import recall_related_mid_term_summaries


@pytest.mark.asyncio
async def test_recall_returns_related_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list(*_a, **_k):
        return [
            {"bot_id": 1, "group_id": 2, "user_id": 3, "created_at": 1, "summary": "群友约定周五晚上八点开黑"},
            {"bot_id": 1, "group_id": 2, "user_id": 3, "created_at": 2, "summary": "阿灿说下周要去漫展"},
        ]

    monkeypatch.setattr(
        "pallas.product.llm.memory.mid_term.list_mid_term_summaries",
        fake_list,
    )

    recalled = await recall_related_mid_term_summaries(bot_id=1, group_id=2, user_id=3, query_text="周五开黑还继续吗")
    assert recalled
    assert "开黑" in recalled[0]["summary"]


@pytest.mark.asyncio
async def test_recall_empty_when_no_related(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list(*_a, **_k):
        return [
            {"bot_id": 1, "group_id": 2, "user_id": 3, "created_at": 1, "summary": "群友约定周五开黑"},
        ]

    monkeypatch.setattr(
        "pallas.product.llm.memory.mid_term.list_mid_term_summaries",
        fake_list,
    )

    recalled = await recall_related_mid_term_summaries(bot_id=1, group_id=2, user_id=3, query_text="今天天气怎么样")
    assert recalled == []


@pytest.mark.asyncio
async def test_recall_respects_min_score_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list(*_a, **_k):
        return [
            {"bot_id": 1, "group_id": 2, "user_id": 3, "created_at": i, "summary": f"讨论鸣潮声骸系统第{i}轮"}
            for i in range(5)
        ]

    monkeypatch.setattr(
        "pallas.product.llm.memory.mid_term.list_mid_term_summaries",
        fake_list,
    )

    recalled = await recall_related_mid_term_summaries(
        bot_id=1, group_id=2, user_id=3, query_text="鸣潮声骸怎么配", limit=2
    )
    assert len(recalled) <= 2
