from __future__ import annotations

from pallas.product.llm.tools import registry as tools_registry  # noqa: F401 — register
from pallas.product.llm.tools.registry import execute_tool, tool_metadata_for_chat, tool_openai_schemas


def test_arknights_tool_schemas_registered() -> None:
    schemas = tool_openai_schemas(domains=frozenset({"arknights"}))
    names = {item["function"]["name"] for item in schemas}
    assert "arknights.operator.get" in names
    assert "arknights.skill.get" in names
    assert "arknights.enemy.get" in names
    assert "arknights.enemy.search" in names


def test_execute_operator_get(monkeypatch) -> None:
    payload = {
        "operators": [
            {
                "id": "char_001",
                "name": "测试干员",
                "profession_cn": "近卫",
                "skills": [{"name": "技能一", "description": "说明"}],
            }
        ]
    }
    monkeypatch.setattr("pallas.core.domain.arknights.query.load_kb_operators_payload", lambda: payload)
    result = execute_tool("arknights.operator.get", {"name": "测试干员"})
    assert result["ok"] is True
    assert result["result"]["found"] is True


def test_execute_enemy_get(monkeypatch) -> None:
    payload = {
        "enemies": [
            {
                "id": "enemy_1",
                "name": "源石虫",
                "level": "NORMAL",
                "description": "野生的被感染生物。",
                "abilities": [],
            }
        ]
    }
    monkeypatch.setattr("pallas.core.domain.arknights.query.load_enemies_payload", lambda: payload)
    result = execute_tool("arknights.enemy.get", {"name": "源石虫"})
    assert result["ok"] is True
    assert result["result"]["found"] is True
    assert result["result"]["enemy"]["name"] == "源石虫"


def test_tool_metadata_for_chat() -> None:
    meta = tool_metadata_for_chat(task="llm_chat", user_text="查一下银灰技能")
    assert meta.get("tools_enabled") is True
    assert isinstance(meta.get("tool_schemas"), list)
    assert meta["tool_schemas"]


def test_tool_metadata_for_operator_lookup_question() -> None:
    meta = tool_metadata_for_chat(task="llm_chat", user_text="你知道谁是银灰吗")
    assert meta.get("tools_enabled") is True
    names = {item["function"]["name"] for item in meta["tool_schemas"]}
    assert "arknights.operator.get" in names


def test_tool_metadata_skips_casual_llm_chat_when_selective() -> None:
    assert tool_metadata_for_chat(task="llm_chat", user_text="今天天气不错") == {}


def test_tool_metadata_skips_empty_llm_chat_when_selective() -> None:
    assert tool_metadata_for_chat(task="llm_chat", user_text="") == {}


def test_tool_metadata_skips_casual_chat_when_selective() -> None:
    assert tool_metadata_for_chat(task="repeater_polish", user_text="今天天气不错") == {}


def test_tool_metadata_skips_repeater_tasks() -> None:
    assert tool_metadata_for_chat(task="repeater_polish") == {}
    assert tool_metadata_for_chat(task="repeater_fallback") == {}
