from __future__ import annotations

import pytest

from pallas.product.llm.tools.select import infer_tool_domains


@pytest.mark.parametrize(
    "text",
    [
        "孤星里克里斯藤最后去了哪里",
        "查一下泰拉年表",
        "想了解角色密录",
    ],
)
def test_prts_lore_questions_infer_prts_domain(text: str) -> None:
    assert "prts" in infer_tool_domains(text)


@pytest.mark.parametrize("text", ["tql 是什么意思", "蛊真人和遮天哪个更好看"])
def test_generic_knowledge_question_does_not_infer_prts_domain(text: str) -> None:
    assert "prts" not in infer_tool_domains(text)
