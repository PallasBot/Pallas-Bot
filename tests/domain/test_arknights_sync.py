from __future__ import annotations

from pallas.core.domain.arknights.sync import (
    build_enemies_payload,
    build_operators_payload,
    duel_sync_plan,
    handbook_info_lines,
    strip_rich,
)


def test_handbook_info_lines_from_info_text() -> None:
    row = {
        "infoTextAudio": [
            {"infoList": [{"infoText": "测试档案一句。"}, {"infoText": "第二句。"}]},
        ],
    }
    lines = handbook_info_lines(row, limit=3)
    assert lines == ["测试档案一句。", "第二句。"]


def test_build_enemies_payload_skips_hidden() -> None:
    table = {
        "enemyData": {
            "enemy_a": {
                "name": "源石虫",
                "description": "野生的被感染生物。",
                "enemyLevel": "NORMAL",
                "hideInHandbook": False,
                "abilityList": [{"text": "无特性"}],
            },
            "enemy_b": {
                "name": "隐藏怪",
                "description": "不应出现",
                "hideInHandbook": True,
            },
        }
    }
    payload = build_enemies_payload(table)
    assert payload["count"] == 1
    assert payload["enemies"][0]["name"] == "源石虫"
    assert payload["enemies"][0]["abilities"] == ["无特性"]


def test_handbook_info_lines_from_nested_story() -> None:
    row = {
        "storyTextAudio": [
            {
                "storyTitle": "基础档案",
                "stories": [
                    {"storyText": "【代号】银灰\n【性别】男\n【出身地】谢拉格"},
                ],
            }
        ],
    }
    lines = handbook_info_lines(row, limit=3)
    assert len(lines) == 1
    assert "基础档案" in lines[0]
    assert "银灰" in lines[0]


def test_build_operators_payload_with_handbook() -> None:
    char_table = {
        "char_001": {
            "name": "测试干员",
            "rarity": "TIER_6",
            "profession": "WARRIOR",
            "nationId": "minos",
            "skills": [],
        }
    }
    skill_table: dict = {}
    handbook = {
        "char_001": {
            "infoTextAudio": [{"infoList": [{"infoText": "档案摘录。"}]}],
        }
    }
    payload = build_operators_payload(char_table, skill_table, handbook)
    op = payload["operators"][0]
    assert op["handbook_lines"] == ["档案摘录。"]
    assert payload.get("handbook_enriched") is True
    assert payload.get("handbook_profiles") == 1


def test_duel_sync_plan_avatars_only() -> None:
    plan = duel_sync_plan(avatars=True, avatars_only=True)
    assert plan.operators is False
    assert plan.avatars is True
    assert plan.avatars_only is True


def test_strip_rich_truncates() -> None:
    long = "a" * 400
    out = strip_rich(long, max_len=10)
    assert len(out) <= 10
    assert out.endswith("…")
