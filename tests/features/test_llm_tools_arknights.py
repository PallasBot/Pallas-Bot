from __future__ import annotations

from src.features.llm.tools import registry as tools_registry  # noqa: F401 — register
from src.features.llm.tools.registry import execute_tool, tool_metadata_for_chat, tool_openai_schemas


def test_arknights_tool_schemas_registered() -> None:
    schemas = tool_openai_schemas(domains=frozenset({"arknights"}))
    names = {item["function"]["name"] for item in schemas}
    assert "arknights.operator.get" in names
    assert "arknights.skill.get" in names


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
    monkeypatch.setattr("src.domain.arknights.query.load_operators_payload", lambda: payload)
    result = execute_tool("arknights.operator.get", {"name": "测试干员"})
    assert result["ok"] is True
    assert result["result"]["found"] is True


def test_tool_metadata_for_chat() -> None:
    meta = tool_metadata_for_chat(task="llm_chat")
    assert meta.get("tools_enabled") is True
    assert isinstance(meta.get("tool_schemas"), list)
    assert meta["tool_schemas"]
