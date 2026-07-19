from __future__ import annotations

import pytest

from pallas.product.llm.tools.identity import is_self_identity_question
from pallas.product.llm.tools.select import infer_tool_domains


@pytest.mark.parametrize(
    "text",
    [
        "你是谁",
        "你是谁？",
        "我又是谁",
        "你知道你是谁吗",
        "@渡月桥 你是谁",
        "[CQ:at,qq=123] 你是谁",
    ],
)
def test_self_identity_does_not_infer_arknights_tools(text: str) -> None:
    assert is_self_identity_question(text)
    assert "arknights" not in infer_tool_domains(text)


@pytest.mark.parametrize(
    "text",
    [
        "银灰是谁",
        "你知道谁是银灰吗",
        "介绍一下能天使",
    ],
)
def test_operator_lookup_still_infers_arknights(text: str) -> None:
    assert not is_self_identity_question(text)
    assert "arknights" in infer_tool_domains(text)
