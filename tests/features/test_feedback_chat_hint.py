from __future__ import annotations

from pallas.product.llm.feedback_chat_hint import correction_matches_query
from pallas.product.persona.self_identity import parse_self_alias_teach


def test_correction_matches_query() -> None:
    assert correction_matches_query("牛牛真棒", "牛牛真棒啊") is True
    assert correction_matches_query("今天好闲", "今天好闲啊") is True
    assert correction_matches_query("牛牛真棒啊", "牛牛真棒") is True
    assert correction_matches_query("今天吃什么", "牛牛真棒") is False
    assert correction_matches_query("", "牛牛") is False
    assert correction_matches_query("牛牛", "") is False


def test_parse_self_alias_teach() -> None:
    assert parse_self_alias_teach("记住：牛牛就是我") == ["牛牛"]
    assert parse_self_alias_teach("记住：牛牛指的是你") == ["牛牛"]
    assert parse_self_alias_teach("牛牛=你") == ["牛牛"]
    assert parse_self_alias_teach("记住：漂亮牛牛就是你") == ["漂亮牛牛"]
    assert parse_self_alias_teach("今天吃什么") == []


def test_parse_self_alias_observe() -> None:
    from pallas.product.persona.self_identity import parse_self_alias_observe

    assert parse_self_alias_observe("大家叫你漂亮牛牛") == ["漂亮牛牛"]
    assert parse_self_alias_observe("你的外号是漂亮牛") == ["漂亮牛"]
    assert parse_self_alias_observe("你是漂亮牛牛") == []
    assert parse_self_alias_observe("你是谁") == []
    assert parse_self_alias_observe("今天吃什么") == []
    # teach 优先，observe 不重复吃
    assert parse_self_alias_observe("漂亮牛牛就是你") == []
