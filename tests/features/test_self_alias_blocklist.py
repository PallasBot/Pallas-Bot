"""self_aliases 收紧：拦截虚词/问句碎片。"""

from __future__ import annotations

from pallas.product.persona.self_identity import (
    extract_self_aliases,
    parse_self_alias_observe,
    parse_self_alias_teach,
)


def test_extract_self_aliases_drops_contaminated() -> None:
    aliases = extract_self_aliases(
        {"self_aliases": ["说的", "这", "哪只牛牛", "傻逼吗", "什么牛", "阿帕"]},
        login_nickname="小牛",
    )
    assert "阿帕" in aliases
    assert "说的" not in aliases
    assert "这" not in aliases
    assert "哪只牛牛" not in aliases
    assert "傻逼吗" not in aliases
    assert "什么牛" not in aliases


def test_parse_observe_rejects_question_fragments() -> None:
    assert parse_self_alias_observe("你是哪只牛牛") == []
    assert parse_self_alias_observe("你是傻逼吗") == []
    assert parse_self_alias_observe("你是真的漂亮牛牛") == []
    assert parse_self_alias_observe("你是她的姐姐") == []
    assert parse_self_alias_observe("大家叫你漂亮牛") == ["漂亮牛"]


def test_parse_teach_still_allows_real_alias() -> None:
    assert parse_self_alias_teach("记住：漂亮牛就是你") == ["漂亮牛"]
    assert parse_self_alias_teach("漂亮牛=你") == ["漂亮牛"]


def test_parse_teach_rejects_negated_identity_statements() -> None:
    assert parse_self_alias_teach("新郎不是我") == []
    assert parse_self_alias_teach("他并不是我") == []
    assert parse_self_alias_teach("这才不是你") == []


def test_parse_teach_rejects_casual_identity_statements() -> None:
    assert parse_self_alias_teach("发了，这是我") == []
    assert parse_self_alias_teach("这张照片是我") == []
    assert parse_self_alias_teach("漂亮牛牛就是你") == []


def test_extract_self_aliases_drops_negation_fragments() -> None:
    aliases = extract_self_aliases({"self_aliases": ["新郎不", "发了，这", "漂亮牛"]})

    assert "新郎不" not in aliases
    assert "发了，这" not in aliases
    assert "漂亮牛" in aliases
