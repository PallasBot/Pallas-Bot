"""方舟干员 LLM tools。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pallas.product.arknights_kb import service
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool

_READ_ONLY = frozenset({ToolCapability.READ_ONLY.value})

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


async def _execute(name: str, args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    _ = ctx
    return await asyncio.to_thread(service.execute_query, name, args)


async def handle_operator_get(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    return await _execute("arknights.operator.get", args, ctx)


async def handle_operator_search(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    return await _execute("arknights.operator.search", args, ctx)


async def handle_skill_get(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    return await _execute("arknights.skill.get", args, ctx)


async def handle_enemy_get(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    return await _execute("arknights.enemy.get", args, ctx)


async def handle_enemy_search(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
    return await _execute("arknights.enemy.search", args, ctx)


_HANDLERS = {
    "arknights.operator.get": handle_operator_get,
    "arknights.operator.search": handle_operator_search,
    "arknights.skill.get": handle_skill_get,
    "arknights.enemy.get": handle_enemy_get,
    "arknights.enemy.search": handle_enemy_search,
}


def register_arknights_tools() -> None:
    for name, contract in service.QUERY_TOOLS.items():
        if not name.startswith("arknights."):
            continue
        register_tool(
            LlmToolSpec(
                name=name,
                description=contract["description"],
                parameters=contract["parameters"],
                domains=frozenset({"arknights"}),
                handler=_HANDLERS[name],
                capabilities=_READ_ONLY,
            )
        )
