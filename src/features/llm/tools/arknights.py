"""方舟干员 LLM tools。"""

from __future__ import annotations

from typing import Any

from src.domain.arknights import query as ark_query
from src.features.llm.tools.registry import LlmToolSpec, register_tool


def register_arknights_tools() -> None:
    register_tool(
        LlmToolSpec(
            name="arknights.operator.get",
            description="按干员中文名查询六星干员基础信息与技能摘要。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "干员中文名，如 银灰"},
                },
                "required": ["name"],
            },
            domains=frozenset({"arknights"}),
            handler=handle_operator_get,
        )
    )
    register_tool(
        LlmToolSpec(
            name="arknights.operator.search",
            description="按关键词模糊搜索干员中文名。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "名称片段"},
                    "limit": {"type": "integer", "description": "最多返回条数", "default": 5},
                },
                "required": ["query"],
            },
            domains=frozenset({"arknights"}),
            handler=handle_operator_search,
        )
    )
    register_tool(
        LlmToolSpec(
            name="arknights.skill.get",
            description="查询指定干员某一技能（1/2/3）的专三描述。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "干员中文名"},
                    "skill_index": {"type": "integer", "description": "技能序号 1-3"},
                },
                "required": ["name", "skill_index"],
            },
            domains=frozenset({"arknights"}),
            handler=handle_skill_get,
        )
    )


def handle_operator_get(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name", "")).strip()
    op = ark_query.query_operator(name)
    if not op:
        return {"found": False, "name": name}
    return {"found": True, "operator": op}


def handle_operator_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 5) or 5)
    items = ark_query.search_operators(query, limit=max(1, min(limit, 10)))
    return {"query": query, "count": len(items), "operators": items}


def handle_skill_get(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name", "")).strip()
    skill_index = int(args.get("skill_index", 0) or 0)
    skill = ark_query.query_operator_skill(name, skill_index)
    if not skill:
        return {"found": False, "name": name, "skill_index": skill_index}
    return {"found": True, "skill": skill}
