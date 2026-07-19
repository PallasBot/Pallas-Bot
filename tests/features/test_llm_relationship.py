from __future__ import annotations

from pallas.product.llm.memory.relationship import (
    extract_at_target,
    normalize_relationship_note,
    parse_relationship_teach,
    relationship_note_has_value,
    relationship_teach_likely,
    resolve_relationship_teach_target_id,
)
from pallas.product.llm.memory.relationship_store import decayed_weight


def test_parse_relationship_teach_prefix() -> None:
    assert parse_relationship_teach("记住关系：阿米娅是罗德岛领袖") == "阿米娅是罗德岛领袖"
    assert parse_relationship_teach("对凯尔希，是医疗组负责人") == "对凯尔希，是医疗组负责人"


def test_parse_relationship_teach_pattern() -> None:
    assert parse_relationship_teach("银灰是我推的角色") == "银灰是我推的角色"


def test_parse_relationship_teach_rejects_emotion() -> None:
    assert parse_relationship_teach("今天烦死了") is None
    assert parse_relationship_teach("随便说点什么") is None
    assert parse_relationship_teach("对我心情不好") is None


def test_parse_relationship_teach_rejects_conversational_dui() -> None:
    assert parse_relationship_teach("对你开枪怎么了") is None
    assert parse_relationship_teach("对他别那么凶") is None
    assert parse_relationship_teach("对啊我是谁") is None


def test_relationship_teach_likely_skips_casual_chat() -> None:
    assert relationship_teach_likely("你好") is False
    assert relationship_teach_likely("对你开枪怎么了") is True
    assert relationship_teach_likely("记住关系：阿米娅是领袖") is True


def test_resolve_relationship_teach_target_id_ignores_at_bot() -> None:
    assert (
        resolve_relationship_teach_target_id(
            "[CQ:at,qq=111] 记住关系：群主",
            speaker_id=222,
            bot_self_id=111,
        )
        == 222
    )
    assert (
        resolve_relationship_teach_target_id(
            "[CQ:at,qq=333] 记住关系：发小",
            speaker_id=222,
            bot_self_id=111,
        )
        == 333
    )


def test_relationship_note_has_value() -> None:
    assert relationship_note_has_value("是这个群的群主") is True
    assert relationship_note_has_value("嗯") is False
    assert relationship_note_has_value("好烦啊") is False


def test_extract_at_target() -> None:
    assert extract_at_target("[CQ:at,qq=12345] 记住关系：群主") == 12345
    assert extract_at_target("没有 at") is None


def test_normalize_relationship_note_truncates() -> None:
    note = normalize_relationship_note("x" * 500, max_len=50)
    assert 0 < len(note) <= 50


def test_decayed_weight_half_life() -> None:
    # 经过一个半衰期后权重约减半
    now = 1_000_000_000
    updated = now - 30 * 86400
    decayed = decayed_weight(1.0, updated, half_life_days=30.0, now=now)
    assert 0.45 < decayed < 0.55


def test_decayed_weight_no_decay_when_disabled() -> None:
    assert decayed_weight(0.8, 0, half_life_days=0.0, now=999) == 0.8
