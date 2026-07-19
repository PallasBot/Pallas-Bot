"""G3：domain 查询 API 与 LLM tool 结果一致（同源 query_operator）。"""

from __future__ import annotations

from pallas.core.domain.arknights.query import query_enemy, query_operator, query_operator_skill
from pallas.product.llm.tools import registry as tools_registry  # noqa: F401 — register
from pallas.product.llm.tools.registry import execute_tool

_OPERATOR_PAYLOAD = {
    "source": "test-fixture",
    "operators": [
        {
            "id": "char_172",
            "name": "银灰",
            "rarity": 6,
            "profession_cn": "近卫",
            "nation_cn": "谢拉格",
            "display_number": "01",
            "item_desc": "喀兰贸易董事长",
            "item_usage": "入职简介摘录",
            "tags": ["输出", "爆发"],
            "skills": [
                {"name": "强力击·γ型", "description": "攻击力与暴击率提升"},
                {"name": "真银斩", "description": "对前方大范围敌人造成物理伤害"},
                {"name": "真银斩·改", "description": "专三描述更长一些用于截断测试" * 3},
            ],
            "handbook_lines": ["档案行一", "档案行二"],
        }
    ],
}

_ENEMY_PAYLOAD = {
    "enemies": [
        {
            "id": "enemy_001",
            "name": "源石虫",
            "level": "NORMAL",
            "description": "野生的被感染生物。",
            "abilities": ["低威胁"],
        }
    ],
}


def test_operator_get_matches_query_operator(monkeypatch) -> None:
    monkeypatch.setattr("pallas.core.domain.arknights.query.load_kb_operators_payload", lambda: _OPERATOR_PAYLOAD)
    direct = query_operator("银灰")
    assert direct is not None
    tool = execute_tool("arknights.operator.get", {"name": "银灰"})
    assert tool["ok"] is True
    assert tool["result"]["found"] is True
    assert tool["result"]["operator"] == direct


def test_operator_get_name_variant_matches_query(monkeypatch) -> None:
    payload = {
        **_OPERATOR_PAYLOAD,
        "operators": [
            *_OPERATOR_PAYLOAD["operators"],
            {
                "id": "char_261",
                "name": "莫斯提马",
                "rarity": 6,
                "profession_cn": "术师",
                "skills": [{"name": "技能一", "description": "说明"}],
            },
        ],
    }
    monkeypatch.setattr("pallas.core.domain.arknights.query.load_kb_operators_payload", lambda: payload)
    direct = query_operator("莫丝提马")
    tool = execute_tool("arknights.operator.get", {"name": "莫丝提马"})
    assert direct is not None
    assert tool["ok"] is True
    assert tool["result"]["operator"] == direct


def test_skill_get_matches_query_operator_skill(monkeypatch) -> None:
    monkeypatch.setattr("pallas.core.domain.arknights.query.load_kb_operators_payload", lambda: _OPERATOR_PAYLOAD)
    direct = query_operator_skill("银灰", 2)
    tool = execute_tool("arknights.skill.get", {"name": "银灰", "skill_index": 2})
    assert direct is not None
    assert tool["ok"] is True
    assert tool["result"]["found"] is True
    assert tool["result"]["skill"] == direct


def test_enemy_get_matches_query_enemy(monkeypatch) -> None:
    monkeypatch.setattr("pallas.core.domain.arknights.query.load_enemies_payload", lambda: _ENEMY_PAYLOAD)
    direct = query_enemy("源石虫")
    tool = execute_tool("arknights.enemy.get", {"name": "源石虫"})
    assert direct is not None
    assert tool["ok"] is True
    assert tool["result"]["found"] is True
    assert tool["result"]["enemy"] == direct
