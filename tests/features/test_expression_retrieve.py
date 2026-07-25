from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pallas.product.persona.expression_bank import ExpressionEntry, append_or_merge_expression


def make_entry(
    *,
    occasion: str,
    saying: str,
    status: str = "shadow",
    source: str = "group_observe",
    affect_hint: str = "neutral",
    bot_id: int = 0,
    support: int = 1,
) -> ExpressionEntry:
    now = int(time.time())
    return ExpressionEntry(
        entry_id=f"{occasion}-{saying}",
        group_id=10001,
        occasion=occasion,
        saying=saying,
        source=source,
        channel="group",
        scene_tier="casual",
        status=status,  # type: ignore[arg-type]
        affect_hint=affect_hint,
        bot_id=bot_id,
        support=support,
        created_at=now,
        updated_at=now,
    )


def test_retrieve_ranks_active_affect_keyword_and_llm_success_entries(monkeypatch, tmp_path) -> None:
    from pallas.product.persona.expression_retrieve import retrieve_expressions_for_message

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_or_merge_expression(make_entry(
        occasion="吐槽加班",
        saying="我也想下班啊",
        status="active",
        source="llm_success",
        affect_hint="complain",
        support=2,
    ))
    append_or_merge_expression(make_entry(
        occasion="日常问候",
        saying="早上好呀",
        status="active",
        affect_hint="warm",
        support=10,
    ))
    append_or_merge_expression(make_entry(
        occasion="吐槽加班",
        saying="太难了",
        status="rejected",
        affect_hint="complain",
        support=99,
    ))

    entries = retrieve_expressions_for_message(10001, "今天加班也太离谱了", limit=3)

    assert [entry.saying for entry in entries] == ["我也想下班啊", "早上好呀"]


def test_retrieve_filters_other_bot_and_builds_reference_block(monkeypatch, tmp_path) -> None:
    from pallas.product.persona.expression_retrieve import (
        build_expression_reference_block,
        retrieve_expressions_for_message,
    )

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    append_or_merge_expression(make_entry(
        occasion="吐槽抽卡",
        saying="又歪了",
        status="active",
        affect_hint="complain",
        bot_id=20002,
    ))
    append_or_merge_expression(make_entry(
        occasion="吐槽抽卡",
        saying="这也太黑了",
        status="active",
        affect_hint="complain",
        bot_id=0,
    ))

    entries = retrieve_expressions_for_message(10001, "抽卡又歪了", limit=5, bot_id=10001)

    assert [entry.saying for entry in entries] == ["这也太黑了"]
    assert build_expression_reference_block(entries) == "\n【表达参考】\n吐槽抽卡→这也太黑了。"


@pytest.mark.asyncio
async def test_context_suffix_respects_inject_config_and_falls_back_to_habits(monkeypatch) -> None:
    from pallas.product.persona import expression_habits as habits

    monkeypatch.setattr(
        habits,
        "get_llm_config",
        lambda: SimpleNamespace(llm_expression_inject_enabled=True, llm_expression_retrieve_limit=2),
    )
    retrieve = Mock(return_value=[SimpleNamespace(occasion="吐槽", saying="太难了")])
    monkeypatch.setattr(habits, "retrieve_expressions_for_message", retrieve)
    assert await habits.build_expression_context_suffix(10001, "太离谱了") == "\n【表达参考】\n吐槽→太难了。"
    retrieve.assert_called_once_with(10001, "太离谱了", limit=2, bot_id=0)

    monkeypatch.setattr(
        habits,
        "get_llm_config",
        lambda: SimpleNamespace(llm_expression_inject_enabled=False, llm_expression_retrieve_limit=2),
    )
    assert await habits.build_expression_context_suffix(
        10001,
        "太离谱了",
        style_profile={"sample": {"affect_triggers": [{"phrase": "牛牛税"}]}},
    ) == "\n【表达习惯参考】群里常接这些说法/梗：牛牛税。"
