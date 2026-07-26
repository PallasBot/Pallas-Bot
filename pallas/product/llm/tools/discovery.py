"""长尾工具发现：deferred 工具可经 tools.find 激活后注入后续轮次。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, register_tool

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext

TOOLS_FIND_NAME = "tools.find"


def search_deferred_tools(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    from pallas.product.llm.tools.overrides import effective_tool_hints, effective_tool_visibility
    from pallas.product.llm.tools.registry import list_registered_tools
    from pallas.product.llm.tools.score import score_tool_text

    scored: list[tuple[int, LlmToolSpec]] = []
    for spec in list_registered_tools():
        if effective_tool_visibility(spec) != "deferred":
            continue
        if spec.name == TOOLS_FIND_NAME:
            continue
        hints = effective_tool_hints(spec)
        score = score_tool_text(query, name=spec.name, description=spec.description, hints=hints)
        if score <= 0:
            continue
        scored.append((score, spec))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    out: list[dict[str, Any]] = []
    for score, spec in scored[: max(1, limit)]:
        out.append({
            "name": spec.name,
            "description": spec.description,
            "score": score,
            "domains": sorted(spec.domains),
        })
    return out


def register_discovery_tools() -> None:
    async def find_handler(args: dict, ctx: ToolInvokeContext | None) -> dict:
        del ctx
        query = str(args.get("query") or args.get("need") or "").strip()
        try:
            limit = int(args.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8
        matches = search_deferred_tools(query, limit=limit)
        return {
            "query": query,
            "matches": matches,
            "activate": [item["name"] for item in matches],
            "hint": "下一轮可直接调用 activate 中的工具名；若列表为空请换关键词。",
        }

    register_tool(
        LlmToolSpec(
            name=TOOLS_FIND_NAME,
            description=(
                "搜索尚未直接暴露的长尾动作工具。用户想找冷门玩法、或已知域工具不够用时调用；"
                "query 写需求关键词（如 点赞、基建）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "需求关键词或简短描述",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数，默认 8",
                    },
                },
                "required": ["query"],
            },
            domains=frozenset({"tools", "meta"}),
            handler=find_handler,
            source=LlmToolSource.BUILTIN,
            capabilities=frozenset({ToolCapability.READ_ONLY.value}),
            hints=frozenset({"找工具", "搜工具", "有什么工具", "能调什么"}),
            visibility="visible",
        )
    )
