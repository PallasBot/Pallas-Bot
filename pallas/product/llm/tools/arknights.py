"""方舟干员 LLM tools。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.core.domain.arknights import query as ark_query
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool

_READ_ONLY = frozenset({ToolCapability.READ_ONLY.value})

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


def register_arknights_tools() -> None:
    register_tool(
        LlmToolSpec(
            name="arknights.operator.get",
            description="按干员中文名查询基础信息、档案摘录、技能摘要与入职简介。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "干员中文名，如 银灰"},
                },
                "required": ["name"],
            },
            domains=frozenset({"arknights"}),
            handler=handle_operator_get,
            capabilities=_READ_ONLY,
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
            capabilities=_READ_ONLY,
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
            capabilities=_READ_ONLY,
        )
    )
    register_tool(
        LlmToolSpec(
            name="arknights.enemy.get",
            description="按敌人中文名查询图鉴基础信息与特性。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "敌人中文名，如 源石虫"},
                },
                "required": ["name"],
            },
            domains=frozenset({"arknights"}),
            handler=handle_enemy_get,
            capabilities=_READ_ONLY,
        )
    )
    register_tool(
        LlmToolSpec(
            name="arknights.enemy.search",
            description="按关键词模糊搜索敌人中文名。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "名称片段"},
                    "limit": {"type": "integer", "description": "最多返回条数", "default": 5},
                },
                "required": ["query"],
            },
            domains=frozenset({"arknights"}),
            handler=handle_enemy_search,
            capabilities=_READ_ONLY,
        )
    )


def handle_operator_get(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    _ = ctx
    name = str(args.get("name", "")).strip()
    op = ark_query.query_operator(name)
    if not op:
        return {"found": False, "name": name}
    return {"found": True, "operator": op}


def handle_operator_search(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    _ = ctx
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 5) or 5)
    items = ark_query.search_operators(query, limit=max(1, min(limit, 10)))
    return {"query": query, "count": len(items), "operators": items}


def handle_skill_get(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    _ = ctx
    name = str(args.get("name", "")).strip()
    skill_index = int(args.get("skill_index", 0) or 0)
    skill = ark_query.query_operator_skill(name, skill_index)
    if not skill:
        return {"found": False, "name": name, "skill_index": skill_index}
    return {"found": True, "skill": skill}


def handle_enemy_get(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    _ = ctx
    name = str(args.get("name", "")).strip()
    row = ark_query.query_enemy(name)
    if not row:
        return {"found": False, "name": name}
    return {"found": True, "enemy": row}


def handle_enemy_search(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    _ = ctx
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 5) or 5)
    items = ark_query.search_enemies(query, limit=max(1, min(limit, 10)))
    return {"query": query, "count": len(items), "enemies": items}
