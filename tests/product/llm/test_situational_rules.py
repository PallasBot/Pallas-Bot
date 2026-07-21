from __future__ import annotations

from pallas.product.llm.situational_rules import (
    format_situational_rules_block,
    load_situational_rules,
    match_situational_rules,
)


def test_match_situational_rules_hits_keyword() -> None:
    rules = [
        {
            "name": "ai_probe",
            "keywords": ["AI", "机器人"],
            "content": "身份试探时别认、别辩，装不懂或换话题。",
            "priority": 100,
        }
    ]
    hits = match_situational_rules("你是不是机器人啊", rules=rules)
    assert len(hits) == 1
    assert hits[0]["name"] == "ai_probe"


def test_match_situational_rules_respects_limit_and_priority() -> None:
    rules = [
        {"name": "low", "keywords": ["测试"], "content": "低优", "priority": 1},
        {"name": "high", "keywords": ["测试"], "content": "高优", "priority": 90},
        {"name": "mid", "keywords": ["测试"], "content": "中优", "priority": 50},
    ]
    hits = match_situational_rules("这是测试", rules=rules, limit=2)
    assert [item["name"] for item in hits] == ["high", "mid"]


def test_format_situational_rules_block() -> None:
    block = format_situational_rules_block([{"name": "x", "content": "看见梗别解释，顺着接。", "keywords": ["梗"]}])
    assert "【情境规则】" in block
    assert "看见梗别解释" in block


def test_default_rules_load_non_empty() -> None:
    rules = load_situational_rules()
    assert isinstance(rules, list)
    assert len(rules) >= 1
