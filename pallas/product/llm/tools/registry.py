"""LLM tool 注册与执行。"""

from __future__ import annotations

import inspect
import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pallas.product.arknights_kb.config import get_arknights_kb_config
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.tools.contracts import (
    ToolAuditInfo,
    ToolCatalogEntry,
    ToolCatalogSelection,
    ToolCatalogSnapshot,
    ToolResultEnvelope,
)
from pallas.product.llm.tools.overrides import load_tool_description_overrides
from pallas.product.llm.tools.select import infer_tool_domains

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext

ToolHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


class LlmToolSource(StrEnum):
    BUILTIN = "builtin"
    PLUGIN_COMMAND = "plugin_command"
    MCP = "mcp"


@dataclass(frozen=True)
class LlmToolResult:
    ok: bool
    result: dict[str, Any] | None = None
    error: str = ""


@dataclass(frozen=True)
class LlmToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    domains: frozenset[str]
    handler: ToolHandler
    source: LlmToolSource = LlmToolSource.BUILTIN
    command_id: str | None = None
    visible_in_ui: bool = True
    capabilities: frozenset[str] = field(default_factory=frozenset)
    plugin_name: str | None = None
    provider_name: str | None = None
    mcp_server_id: str | None = None


_REGISTRY: list[LlmToolSpec] = []
_REGISTERED_NAMES: set[str] = set()


def ensure_tools_loaded() -> None:
    from pallas.product.llm.tools.bootstrap import ensure_llm_tools_bootstrapped

    ensure_llm_tools_bootstrapped()


def clear_tool_registry() -> None:
    _REGISTRY.clear()
    _REGISTERED_NAMES.clear()


def register_tool(spec: LlmToolSpec) -> None:
    if spec.name in _REGISTERED_NAMES:
        return
    _REGISTRY.append(spec)
    _REGISTERED_NAMES.add(spec.name)


def iter_registered_tools(
    *,
    domains: frozenset[str] | None = None,
    source: LlmToolSource | None = None,
) -> tuple[LlmToolSpec, ...]:
    ensure_tools_loaded()
    items = tuple(_REGISTRY)
    if domains is not None:
        items = tuple(spec for spec in items if spec.domains.intersection(domains))
    if source is not None:
        items = tuple(spec for spec in items if spec.source == source)
    return items


def list_registered_tools() -> tuple[LlmToolSpec, ...]:
    return iter_registered_tools()


def trim_tool_description(description: str, *, max_len: int) -> str:
    text = (description or "").strip()
    if max_len <= 0 or len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def tool_catalog_entry_from_spec(spec: LlmToolSpec, *, description: str | None = None) -> ToolCatalogEntry:
    return ToolCatalogEntry(
        name=spec.name,
        description=description if description is not None else spec.description,
        parameters=spec.parameters,
        source=spec.source.value,
        domains=sorted(spec.domains),
        capabilities=sorted(spec.capabilities),
        audit=ToolAuditInfo(
            command_id=spec.command_id,
            plugin_name=spec.plugin_name,
            provider_name=spec.provider_name,
            mcp_server_id=spec.mcp_server_id,
        ),
    )


def normalize_tool_result(raw: Any, *, spec: LlmToolSpec | None = None) -> dict[str, Any]:
    if isinstance(raw, dict) and "ok" in raw:
        ok = bool(raw.get("ok"))
        result = raw.get("result")
        if result is not None and not isinstance(result, dict):
            result = {"value": result}
        error = str(raw.get("error") or "")
    elif isinstance(raw, dict):
        ok = True
        result = raw
        error = ""
    elif raw is None:
        ok = True
        result = None
        error = ""
    else:
        ok = True
        result = {"value": raw}
        error = ""

    envelope = ToolResultEnvelope(
        ok=ok,
        result=result,
        error=error,
        source=spec.source.value if spec is not None else "",
        audit=ToolAuditInfo(
            command_id=spec.command_id if spec is not None else None,
            plugin_name=spec.plugin_name if spec is not None else None,
            provider_name=spec.provider_name if spec is not None else None,
            mcp_server_id=spec.mcp_server_id if spec is not None else None,
        ),
    )
    return envelope.model_dump(mode="json")


def iter_eligible_tool_specs(*, domains: frozenset[str] | None = None) -> tuple[LlmToolSpec, ...]:
    cfg = get_llm_config()
    if not cfg.llm_tools_enabled:
        return ()
    ensure_tools_loaded()
    kb = get_arknights_kb_config()
    blacklist = {item.strip().lower() for item in cfg.llm_tools_blacklist if item.strip()}
    items: list[LlmToolSpec] = []
    for spec in iter_registered_tools(domains=domains):
        if blacklist:
            if spec.name.lower() in blacklist:
                continue
            if spec.domains.intersection(blacklist):
                continue
        if "arknights" in spec.domains and not kb.arknights_kb_enabled:
            continue
        items.append(spec)
    return tuple(items)


def catalog_entry_for_spec(spec: LlmToolSpec) -> ToolCatalogEntry:
    cfg = get_llm_config()
    description = trim_tool_description(spec.description, max_len=cfg.llm_tools_desc_max_len)
    override = load_tool_description_overrides().get(spec.name)
    if isinstance(override, dict):
        custom = str(override.get("description") or "").strip()
        if custom:
            description = trim_tool_description(custom, max_len=cfg.llm_tools_desc_max_len)
    return tool_catalog_entry_from_spec(spec, description=description)


def openai_schemas_from_catalog(catalog: ToolCatalogSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": item.name,
                "description": item.description,
                "parameters": item.parameters,
            },
        }
        for item in catalog.tools
    ]


def tool_catalog_for_chat(*, task: str | None = None, user_text: str = "") -> ToolCatalogSnapshot | None:
    normalized = str(task or "").strip().lower()
    if normalized in _NO_TOOL_TASKS:
        return None
    cfg = get_llm_config()
    domains: frozenset[str] | None = None
    inferred_domains: list[str] = []
    if cfg.llm_tools_selective:
        inferred = infer_tool_domains(user_text)
        if not inferred:
            return None
        domains = inferred
        inferred_domains = sorted(inferred)
    specs = iter_eligible_tool_specs(domains=domains)
    if not specs:
        return None
    entries = [catalog_entry_for_spec(spec) for spec in specs]
    return ToolCatalogSnapshot(
        tools=entries,
        selection=ToolCatalogSelection(
            tools_enabled=True,
            selective_enabled=bool(cfg.llm_tools_selective),
            inferred_domains=inferred_domains,
            schema_count=len(entries),
        ),
    )


def tool_openai_schemas(*, domains: frozenset[str] | None = None) -> list[dict[str, Any]]:
    specs = iter_eligible_tool_specs(domains=domains)
    if not specs:
        return []
    catalog = ToolCatalogSnapshot(
        tools=[catalog_entry_for_spec(spec) for spec in specs],
        selection=ToolCatalogSelection(tools_enabled=True, schema_count=len(specs)),
    )
    return openai_schemas_from_catalog(catalog)


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
            if spec.source == LlmToolSource.MCP:
                from pallas.product.llm.tools.mcp_bootstrap import execute_mcp_tool_async

                result = await execute_mcp_tool_async(spec, args)
                return normalize_tool_result(result, spec=spec)
            result = spec.handler(args, context)
            if inspect.isawaitable(result):
                result = await result
            return normalize_tool_result(result, spec=spec)
        except Exception as exc:
            return normalize_tool_result({"ok": False, "error": str(exc)}, spec=spec)
    return normalize_tool_result({"ok": False, "error": f"unknown tool: {name}"})


def execute_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """同步入口（无群上下文）；命令类 tool 需走 execute_tool_async。"""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(execute_tool_async(name, arguments, context=None))
    msg = "execute_tool cannot run async command tools inside event loop; use execute_tool_async"
    raise RuntimeError(msg)


_NO_TOOL_TASKS = frozenset({"repeater_fallback", "repeater_polish", "repeater_polish_lite", "repeater_select", "drunk"})


def tool_metadata_for_chat(*, task: str | None = None, user_text: str = "") -> dict[str, Any]:
    """写入 AI 仓 metadata：tool_catalog + 兼容字段 tools_enabled / tool_schemas。"""
    catalog = tool_catalog_for_chat(task=task, user_text=user_text)
    if catalog is None:
        return {}
    schemas = openai_schemas_from_catalog(catalog)
    return {
        "tools_enabled": True,
        "tool_catalog": catalog.model_dump(mode="json"),
        "tool_schemas": schemas,
        "tool_schema_count": int(catalog.selection.schema_count),
    }


def build_tools_ui_rows() -> list[dict[str, Any]]:
    ensure_tools_loaded()
    rows = [
        {
            "name": spec.name,
            "description": spec.description,
            "domains": sorted(spec.domains),
            "command_id": spec.command_id,
            "source": spec.source.value,
        }
        for spec in iter_registered_tools()
        if spec.visible_in_ui
    ]
    rows.sort(key=operator.itemgetter("name"))
    return rows
