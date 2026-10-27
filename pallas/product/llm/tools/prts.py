"""内建 PRTS 只读语料 LLM tools。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pallas.product.arknights_kb import service
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool

_READ_ONLY = frozenset({ToolCapability.READ_ONLY.value})

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


def _handler_for(name: str):
    async def handler(args: dict[str, Any], ctx: ToolInvokeContext | None = None) -> dict[str, Any]:
        _ = ctx
        return await asyncio.to_thread(service.execute_query, name, args)

    return handler


def register_prts_tools() -> None:
    for name, contract in service.QUERY_TOOLS.items():
        if not name.startswith("prts."):
            continue
        register_tool(
            LlmToolSpec(
                name=name,
                description=contract["description"],
                parameters=contract["parameters"],
                domains=frozenset({"prts"}),
                handler=_handler_for(name),
                capabilities=_READ_ONLY,
                max_execution_ms=60_000,
            )
        )
