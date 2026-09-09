from __future__ import annotations

import pytest

from pallas.product.llm.tools.select import infer_tool_domains


@pytest.mark.parametrize(
    "text",
    [
        "明日方舟孤星剧情发生在什么时候",
        "方舟里克丽斯腾最后去了哪里",
        "泰拉年表里孤星是哪一年",
        "PRTS 查一下这句台词",
    ],
)
def test_prts_lore_questions_infer_prts_domain(text: str) -> None:
    assert "prts" in infer_tool_domains(text)


@pytest.mark.parametrize(
    "text",
    [
        "tql 是什么意思",
        "蛊真人和遮天哪个更好看",
        "这个电影的世界观是什么",
        "这句台词什么意思",
        "某角色档案怎么看",
    ],
)
def test_generic_knowledge_question_does_not_infer_prts_domain(text: str) -> None:
    assert "prts" not in infer_tool_domains(text)


def test_external_scope_matcher_can_recall_data_backed_prts_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.tools.external.external_llm_domains_for_text",
        lambda text: frozenset({"prts"}) if "孤星" in text else frozenset(),
    )

    assert "prts" in infer_tool_domains("孤星剧情发生在什么时候")
