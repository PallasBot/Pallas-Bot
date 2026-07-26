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
    hints: frozenset[str] = field(default_factory=frozenset)
    visibility: str = "visible"


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


def to_provider_tool_name(name: str) -> str:
    """OpenAI / DeepSeek 等要求 function.name 匹配 ^[a-zA-Z0-9_-]+$，点号改为双下划线。"""
    return str(name or "").strip().replace(".", "__")


def from_provider_tool_name(name: str) -> str:
    """把 provider 侧名称还原为 registry 名；已是 registry 名则原样返回。"""
    raw = str(name or "").strip()
    if not raw:
        return raw
    if raw in _REGISTERED_NAMES:
        return raw
    if "__" not in raw:
        return raw
    dotted = raw.replace("__", ".")
    if dotted in _REGISTERED_NAMES:
        return dotted
    return dotted


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
        elif result is None:
            # 兼容旧 handler：ok 与细节平铺在顶层时，收拢进 result 供模型阅读
            extras = {
                key: value
                for key, value in raw.items()
                if key not in {"ok", "error", "result", "source", "audit"}
            }
            result = extras or None
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
                "name": to_provider_tool_name(item.name),
                "description": item.description,
                "parameters": item.parameters,
            },
        }
        for item in catalog.tools
    ]


def filter_specs_for_chat_visibility(
    specs: tuple[LlmToolSpec, ...],
    *,
    user_text: str = "",
    activated_names: frozenset[str] | None = None,
) -> tuple[LlmToolSpec, ...]:
    """visible 随域注入；deferred 仅 hints 命中或已被 activate。"""
    from pallas.product.llm.tools.select import deferred_tools_matched_by_hints

    activated = activated_names or frozenset()
    hint_hits = deferred_tools_matched_by_hints(user_text) if user_text else frozenset()
    out: list[LlmToolSpec] = []
    for spec in specs:
        vis = str(spec.visibility or "visible").strip().lower()
        if vis != "deferred":
            out.append(spec)
            continue
        if spec.name in activated or spec.name in hint_hits:
            out.append(spec)
    return tuple(out)


def tool_catalog_for_chat(
    *,
    task: str | None = None,
    user_text: str = "",
    activated_names: frozenset[str] | None = None,
) -> ToolCatalogSnapshot | None:
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
    specs = filter_specs_for_chat_visibility(
        specs,
        user_text=user_text,
        activated_names=activated_names,
    )
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
    resolved = from_provider_tool_name(name)
    for spec in _REGISTRY:
        if spec.name != resolved:
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
    """写入 Bot 工具 metadata：tool_catalog + 兼容字段 tools_enabled / tool_schemas。"""
    catalog = tool_catalog_for_chat(task=task, user_text=user_text)
    if catalog is None:
        return {}
    schemas = openai_schemas_from_catalog(catalog)
    payload: dict[str, Any] = {
        "tools_enabled": True,
        "tool_catalog": catalog.model_dump(mode="json"),
        "tool_schemas": schemas,
        "tool_schema_count": int(catalog.selection.schema_count),
    }
    # 选择性命中且全部为插件口令工具时，首轮要求必须调工具，避免只口头答应
    if catalog.selection.selective_enabled and catalog.tools:
        sources = {str(item.source or "") for item in catalog.tools}
        if sources and sources <= {LlmToolSource.PLUGIN_COMMAND.value}:
            payload["tool_choice_prefer"] = "required"
    return payload


def build_tools_catalog_ui() -> dict[str, Any]:
    """WebUI 只读工具清单：全量可见 tool + 当前策略门闸。"""
    from pallas.product.llm.tools.metadata import iter_package_declared_llm_tools

    cfg = get_llm_config()
    kb = get_arknights_kb_config()
    ensure_tools_loaded()
    blacklist = {item.strip().lower() for item in cfg.llm_tools_blacklist if item.strip()}
    eligible_names = {spec.name for spec in iter_eligible_tool_specs()}
    items: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for spec in iter_registered_tools():
        if not spec.visible_in_ui:
            continue
        entry = catalog_entry_for_spec(spec)
        disabled_reason: str | None = None
        if not cfg.llm_tools_enabled:
            disabled_reason = "tools_disabled"
        elif spec.name.lower() in blacklist or spec.domains.intersection(blacklist):
            disabled_reason = "blacklisted"
        elif "arknights" in spec.domains and not kb.arknights_kb_enabled:
            disabled_reason = "arknights_kb_disabled"
        items.append({
            "name": entry.name,
            "description": entry.description,
            "parameters": entry.parameters,
            "source": entry.source,
            "domains": list(entry.domains),
            "capabilities": list(entry.capabilities),
            "command_id": entry.audit.command_id,
            "plugin_name": entry.audit.plugin_name,
            "provider_name": entry.audit.provider_name,
            "mcp_server_id": entry.audit.mcp_server_id,
            "eligible": spec.name in eligible_names,
            "disabled_reason": disabled_reason,
        })
        seen_names.add(entry.name)
    # 分片 hub 不加载 drink/llm_chat：把 packages 声明补进只读清单，便于对照
    for plugin_name, _title, decl in iter_package_declared_llm_tools():
        if decl.name in seen_names:
            continue
        disabled_reason = "plugin_not_in_process"
        if not cfg.llm_tools_enabled:
            disabled_reason = "tools_disabled"
        elif decl.name.lower() in blacklist:
            disabled_reason = "blacklisted"
        items.append({
            "name": decl.name,
            "description": decl.description,
            "parameters": decl.parameters or {"type": "object", "properties": {}},
            "source": LlmToolSource.PLUGIN_COMMAND.value,
            "domains": ["command", plugin_name],
            "capabilities": ["side_effecting", "requires_group_context"],
            "command_id": decl.command_id,
            "plugin_name": plugin_name,
            "provider_name": None,
            "mcp_server_id": None,
            "eligible": False,
            "disabled_reason": disabled_reason,
        })
        seen_names.add(decl.name)
    items.sort(key=operator.itemgetter("name"))
    return {
        "items": items,
        "count": len(items),
        "policy": {
            "tools_enabled": bool(cfg.llm_tools_enabled),
            "selective_enabled": bool(cfg.llm_tools_selective),
            "max_rounds": int(cfg.llm_tools_max_rounds),
            "blacklist": [str(item) for item in (cfg.llm_tools_blacklist or []) if str(item).strip()],
            "arknights_kb_enabled": bool(kb.arknights_kb_enabled),
            "desc_max_len": int(cfg.llm_tools_desc_max_len),
        },
    }


def build_tools_ui_rows() -> list[dict[str, Any]]:
    return list(build_tools_catalog_ui().get("items") or [])
