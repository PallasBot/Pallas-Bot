from __future__ import annotations

from pallas.core.domain.arknights.query import query_operator, query_operator_skill, search_operators


def test_query_operator_by_name() -> None:
    payload = {
        "source": "test",
        "operators": [
            {
                "id": "char_001",
                "name": "银灰",
                "profession_cn": "近卫",
                "nation_cn": "谢拉格",
                "skills": [
                    {"name": "强力击", "description": "下次攻击力提升"},
                    {"name": "雪境生存法则", "description": "防御力提升"},
                    {"name": "真银斩", "description": "范围物理伤害"},
                ],
            }
        ],
    }
    op = query_operator("银灰", payload=payload)
    assert op is not None
    assert op["name"] == "银灰"
    assert len(op["skills"]) == 3


def test_search_operators_partial() -> None:
    payload = {
        "operators": [
            {"id": "a", "name": "银灰", "skills": []},
            {"id": "b", "name": "银老板", "skills": []},
            {"id": "c", "name": "能天使", "skills": []},
        ]
    }
    hits = search_operators("银", payload=payload, limit=5)
    assert len(hits) == 2


def test_query_enemy_by_name() -> None:
    from pallas.core.domain.arknights.query import query_enemy

    payload = {
        "source": "test",
        "enemies": [
            {
                "id": "enemy_1",
                "name": "源石虫",
                "level": "NORMAL",
                "description": "野生的被感染生物。",
                "abilities": [],
            }
        ],
    }
    row = query_enemy("源石虫", payload=payload)
    assert row is not None
    assert row["name"] == "源石虫"


def test_query_operator_skill_index() -> None:
    payload = {
        "operators": [
            {
                "id": "char_001",
                "name": "银灰",
                "skills": [
                    {"name": "一", "description": "d1"},
                    {"name": "二", "description": "d2"},
                    {"name": "真银斩", "description": "d3"},
                ],
            }
        ],
    }
    skill = query_operator_skill("银灰", 3, payload=payload)
    assert skill is not None
    assert skill["skill_name"] == "真银斩"
    assert skill["description"] == "d3"


def test_query_operator_si_si_typo() -> None:
    payload = {
        "operators": [
            {
                "id": "char_4087_ines",
                "name": "伊内丝",
                "skills": [{"name": "独影归途", "description": "专三描述"}],
            }
        ],
    }
    op = query_operator("伊内斯", payload=payload)
    assert op is not None
    assert op["name"] == "伊内丝"
    hits = search_operators("伊内斯", payload=payload)
    assert hits
    assert hits[0]["name"] == "伊内丝"
