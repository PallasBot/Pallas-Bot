"""LLM tool 注册与执行。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.features.arknights_kb.config import get_arknights_kb_config
from src.features.llm.config import get_llm_config

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class LlmToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    domains: frozenset[str]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


_REGISTRY: list[LlmToolSpec] = []


def register_tool(spec: LlmToolSpec) -> None:
    _REGISTRY.append(spec)


def list_registered_tools() -> tuple[LlmToolSpec, ...]:
    return tuple(_REGISTRY)


def tool_openai_schemas(*, domains: frozenset[str] | None = None) -> list[dict[str, Any]]:
    cfg = get_llm_config()
    if not cfg.llm_tools_enabled:
        return []
    kb = get_arknights_kb_config()
    if not kb.arknights_kb_enabled and domains and "arknights" in domains:
        return []
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


def execute_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    for spec in _REGISTRY:
        if spec.name != name:
            continue
        try:
            result = spec.handler(args)
            if isinstance(result, dict):
                return {"ok": True, "result": result}
            return {"ok": True, "result": {"value": result}}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": f"unknown tool: {name}"}


def tool_metadata_for_chat(*, task: str | None = None) -> dict[str, Any]:
    """写入 AI 仓 metadata：tools_enabled + tool_schemas。"""
    _ = task
    schemas = tool_openai_schemas(domains=frozenset({"arknights"}))
    if not schemas:
        return {}
    return {"tools_enabled": True, "tool_schemas": schemas}
