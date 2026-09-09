"""社区插件注册只读 LLM tools 的桥接层。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ExternalToolHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ExternalLlmToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    domains: frozenset[str]
    handler: ExternalToolHandler
    plugin_name: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    hints: frozenset[str] = field(default_factory=frozenset)
    visibility: str = "deferred"
    max_execution_ms: int = 10_000


_DEFINITIONS: dict[str, ExternalLlmToolDefinition] = {}


def register_external_llm_tool(
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
    domains: set[str] | frozenset[str],
    handler: ExternalToolHandler,
    plugin_name: str,
    capabilities: set[str] | frozenset[str] = frozenset(),
    hints: set[str] | frozenset[str] = frozenset(),
    visibility: str = "deferred",
    max_execution_ms: int = 10_000,
) -> None:
    definition = ExternalLlmToolDefinition(
        name=name.strip(),
        description=description.strip(),
        parameters=parameters,
        domains=frozenset(item.strip() for item in domains if item.strip()),
        handler=handler,
        plugin_name=plugin_name.strip(),
        capabilities=frozenset(item.strip() for item in capabilities if item.strip()),
        hints=frozenset(item.strip() for item in hints if item.strip()),
        visibility=visibility.strip() or "deferred",
        max_execution_ms=max(1, int(max_execution_ms)),
    )
    if not definition.name or not definition.description or not definition.plugin_name:
        raise ValueError("name、description 与 plugin_name 不能为空")
    _DEFINITIONS[definition.name] = definition
    register_external_llm_tools()


def register_external_llm_tools() -> int:
    from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec, register_tool

    registered = 0
    for definition in _DEFINITIONS.values():
        capabilities = set(definition.capabilities)
        register_tool(
            LlmToolSpec(
                name=definition.name,
                description=definition.description,
                parameters=definition.parameters,
                domains=definition.domains,
                handler=definition.handler,
                source=LlmToolSource.PLUGIN,
                plugin_name=definition.plugin_name,
                capabilities=frozenset(capabilities),
                hints=definition.hints,
                visibility=definition.visibility,
                read_only="read_only" in capabilities,
                reversible="read_only" in capabilities,
                max_execution_ms=definition.max_execution_ms,
            )
        )
        registered += 1
    return registered


def clear_external_llm_tools_for_tests() -> None:
    _DEFINITIONS.clear()
