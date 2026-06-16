"""LLM tool 注册与执行。"""

from __future__ import annotations

import inspect
import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.features.arknights_kb.config import get_arknights_kb_config
from src.features.llm.config import get_llm_config

if TYPE_CHECKING:
    from src.features.llm.tools.context import ToolInvokeContext

ToolHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class LlmToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    domains: frozenset[str]
    handler: ToolHandler
    command_id: str | None = None


_REGISTRY: list[LlmToolSpec] = []
_REGISTERED_NAMES: set[str] = set()


def ensure_tools_loaded() -> None:
    from src.features.llm.tools.bootstrap import ensure_llm_tools_bootstrapped

    ensure_llm_tools_bootstrapped()


def clear_tool_registry() -> None:
    _REGISTRY.clear()
    _REGISTERED_NAMES.clear()


def register_tool(spec: LlmToolSpec) -> None:
    if spec.name in _REGISTERED_NAMES:
        return
    _REGISTRY.append(spec)
    _REGISTERED_NAMES.add(spec.name)


def list_registered_tools() -> tuple[LlmToolSpec, ...]:
    ensure_tools_loaded()
    return tuple(_REGISTRY)


def tool_openai_schemas(*, domains: frozenset[str] | None = None) -> list[dict[str, Any]]:
    cfg = get_llm_config()
    if not cfg.llm_tools_enabled:
        return []
    ensure_tools_loaded()
    kb = get_arknights_kb_config()
    allowed = domains
    out: list[dict[str, Any]] = []
    for spec in _REGISTRY:
        if allowed is not None and not spec.domains.intersection(allowed):
            continue
        if "arknights" in spec.domains and not kb.arknights_kb_enabled:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        })
    return out


async def execute_tool_async(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    context: ToolInvokeContext | None = None,
) -> dict[str, Any]:
    ensure_tools_loaded()
    args = arguments if isinstance(arguments, dict) else {}
    for spec in _REGISTRY:
        if spec.name != name:
            continue
        try:
            result = spec.handler(args, context)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, dict):
                if "ok" in result:
                    return result
                return {"ok": True, "result": result}
            return {"ok": True, "result": {"value": result}}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": f"unknown tool: {name}"}


def execute_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """同步入口（无群上下文）；命令类 tool 需走 execute_tool_async。"""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(execute_tool_async(name, arguments, context=None))
    msg = "execute_tool cannot run async command tools inside event loop; use execute_tool_async"
    raise RuntimeError(msg)


def tool_metadata_for_chat(*, task: str | None = None) -> dict[str, Any]:
    """写入 AI 仓 metadata：tools_enabled + tool_schemas。"""
    _ = task
    schemas = tool_openai_schemas()
    if not schemas:
        return {}
    return {"tools_enabled": True, "tool_schemas": schemas}


def build_tools_ui_rows() -> list[dict[str, Any]]:
    ensure_tools_loaded()
    rows = [
        {
            "name": spec.name,
            "description": spec.description,
            "domains": sorted(spec.domains),
            "command_id": spec.command_id,
        }
        for spec in _REGISTRY
    ]
    rows.sort(key=operator.itemgetter("name"))
    return rows
