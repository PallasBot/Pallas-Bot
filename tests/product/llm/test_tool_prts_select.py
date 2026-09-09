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


def test_generic_knowledge_question_infers_knowledge_domain() -> None:
    assert "knowledge" in infer_tool_domains("谢拉格战舰是什么时候造的")
