"""LLM tool 注册与执行。"""

from __future__ import annotations

import asyncio
import inspect
import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pallas.core.platform.ingress.plugin_command_plaintext import is_plugin_command_plaintext
from pallas.product.arknights_kb.config import get_arknights_kb_config
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.tools.contracts import (
    ToolAuditInfo,
    ToolCatalogEntry,
    ToolCatalogSelection,
    ToolCatalogSnapshot,
    ToolResultEnvelope,
)
from pallas.product.llm.tools.overrides import (
    effective_tool_hints,
    effective_tool_visibility,
    load_tool_description_overrides,
    load_tool_overrides,
    tool_override_disabled,
)
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
    estimated_duration_ms: int = 0
    cost_hint: str = ""
    read_only: bool = False
    approval_required: bool = False
    reversible: bool = False
    idempotency_key: str = ""
    max_execution_ms: int = 10000
    background_ok: bool = False
    display_mode: str = "default"


_REGISTRY: list[LlmToolSpec] = []
_REGISTERED_NAMES: set[str] = set()
_IDEMPOTENT_RESULTS: dict[tuple[str, int | None, int | None, int | None, str], dict[str, Any]] = {}


def ensure_tools_loaded() -> None:
    from pallas.product.llm.tools.bootstrap import ensure_llm_tools_bootstrapped

    ensure_llm_tools_bootstrapped()


def clear_tool_registry() -> None:
    _REGISTRY.clear()
    _REGISTERED_NAMES.clear()
    _IDEMPOTENT_RESULTS.clear()


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
    read_only = spec.read_only or "read_only" in spec.capabilities
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
        estimated_duration_ms=spec.estimated_duration_ms,
        cost_hint=spec.cost_hint,
        read_only=read_only,
        approval_required=spec.approval_required,
        reversible=spec.reversible or read_only,
        idempotency_key=spec.idempotency_key,
        max_execution_ms=spec.max_execution_ms,
        background_ok=spec.background_ok,
        display_mode=spec.display_mode,
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
                key: value for key, value in raw.items() if key not in {"ok", "error", "result", "source", "audit"}
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
        if tool_override_disabled(spec.name):
            continue
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
        vis = effective_tool_visibility(spec)
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
    from pallas.product.llm.tools.inventory import is_inventory_intent, is_query_tool, merge_inventory_overlay_specs

    normalized = str(task or "").strip().lower()
    if normalized in _NO_TOOL_TASKS:
        return None
    if user_text and is_plugin_command_plaintext(user_text):
        return None
    cfg = get_llm_config()
    inventory = is_inventory_intent(user_text)
    domains: frozenset[str] | None = None
    inferred_domains: list[str] = []
    selection_source = "all"
    soft_fields: dict[str, Any] = {
        "soft_recall_confidence": 0,
        "soft_recall_candidates": [],
        "semantic_recall_confidence": 0,
        "semantic_recall_candidates": [],
        "ask_before_call": False,
        "missing_required_params": {},
    }
    soft_hits = None
    if cfg.llm_tools_selective:
        inferred = infer_tool_domains(user_text)
        if inferred:
            domains = inferred
            inferred_domains = sorted(inferred)
            selection_source = "selective"
        elif bool(getattr(cfg, "llm_tools_soft_recall_enabled", True)):
            from pallas.product.llm.tools.soft_recall import (
                select_soft_recall_hits,
                soft_recall_snapshot_fields,
            )

            soft_hits = select_soft_recall_hits(
                user_text,
                min_score=int(getattr(cfg, "llm_tools_soft_recall_min_score", 6) or 6),
                max_candidates=int(getattr(cfg, "llm_tools_soft_recall_max_candidates", 3) or 3),
            )
            if soft_hits:
                selection_source = "soft_recall"
                soft_fields = soft_recall_snapshot_fields(soft_hits)
            elif inventory:
                selection_source = "inventory"
            else:
                return None
        elif inventory:
            selection_source = "inventory"
        else:
            return None
    if soft_hits is not None:
        specs_list = [hit.spec for hit in soft_hits]
    elif selection_source == "inventory":
        specs_list = []
    else:
        specs_list = list(
            filter_specs_for_chat_visibility(
                iter_eligible_tool_specs(domains=domains),
                user_text=user_text,
                activated_names=activated_names,
            )
        )
    if inventory and cfg.llm_tools_selective:
        specs_list = merge_inventory_overlay_specs(
            specs_list,
            user_text=user_text,
            domains=domains,
            soft_recall_min_score=int(getattr(cfg, "llm_tools_soft_recall_min_score", 6) or 6),
            soft_recall_max_candidates=int(getattr(cfg, "llm_tools_soft_recall_max_candidates", 3) or 3),
        )
        # 盘点口语只留查询类，避免 memes.recommend 直接出图抢答
        query_only = [spec for spec in specs_list if is_query_tool(spec)]
        if query_only:
            specs_list = query_only
        if selection_source == "selective":
            selection_source = "selective+inventory"
        elif selection_source == "soft_recall":
            selection_source = "soft_recall+inventory"
    if domains and not inventory and len(specs_list) > 1 and bool(getattr(cfg, "llm_tools_soft_recall_enabled", True)):
        from pallas.product.llm.tools.soft_recall import select_soft_recall_hits, soft_recall_snapshot_fields

        ranked_hits = select_soft_recall_hits(
            user_text,
            min_score=int(getattr(cfg, "llm_tools_soft_recall_min_score", 6) or 6),
            max_candidates=int(getattr(cfg, "llm_tools_soft_recall_max_candidates", 3) or 3),
            eligible_specs=tuple(specs_list),
        )
        if ranked_hits:
            specs_list = [hit.spec for hit in ranked_hits]
            soft_fields = soft_recall_snapshot_fields(ranked_hits)
            selection_source = f"{selection_source}+ranked"
        else:
            from pallas.product.llm.tools.semantic_recall import (
                select_semantic_recall_hits,
                semantic_recall_snapshot_fields,
            )

            semantic_hits = select_semantic_recall_hits(
                user_text,
                eligible_specs=tuple(specs_list),
                cfg=cfg,
                max_candidates=int(getattr(cfg, "llm_tools_soft_recall_max_candidates", 3) or 3),
            )
            if semantic_hits:
                specs_list = [hit.spec for hit in semantic_hits]
                soft_fields.update(semantic_recall_snapshot_fields(semantic_hits))
                selection_source = f"{selection_source}+semantic"
    if not specs_list:
        return None
    entries = [catalog_entry_for_spec(spec) for spec in specs_list]
    return ToolCatalogSnapshot(
        tools=entries,
        selection=ToolCatalogSelection(
            tools_enabled=True,
            selective_enabled=bool(cfg.llm_tools_selective),
            inferred_domains=inferred_domains,
            schema_count=len(entries),
            selection_source=selection_source,
            soft_recall_confidence=int(soft_fields.get("soft_recall_confidence") or 0),
            soft_recall_candidates=list(soft_fields.get("soft_recall_candidates") or []),
            semantic_recall_confidence=int(soft_fields.get("semantic_recall_confidence") or 0),
            semantic_recall_candidates=list(soft_fields.get("semantic_recall_candidates") or []),
            ask_before_call=bool(soft_fields.get("ask_before_call")),
            missing_required_params=dict(soft_fields.get("missing_required_params") or {}),
            inventory_intent=bool(inventory),
        ),
    )


def tool_openai_schemas(*, domains: frozenset[str] | None = None) -> list[dict[str, Any]]:
    specs = iter_eligible_tool_specs(domains=domains)
    if not specs:
        return []
    catalog = ToolCatalogSnapshot(
        tools=[catalog_entry_for_spec(spec) for spec in specs],
        selection=ToolCatalogSelection(tools_enabled=True, schema_count=len(specs), selection_source="all"),
    )
    return openai_schemas_from_catalog(catalog)


async def execute_tool_async(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    context: ToolInvokeContext | None = None,
    background: bool = False,
) -> dict[str, Any]:
    ensure_tools_loaded()
    args = arguments if isinstance(arguments, dict) else {}
    resolved = from_provider_tool_name(name)
    for spec in _REGISTRY:
        if spec.name != resolved:
            continue
        if spec.approval_required and (context is None or not context.is_tool_approved(spec.name)):
            return normalize_tool_result({"ok": False, "error": "approval_required"}, spec=spec)
        if background:
            if not spec.background_ok:
                return normalize_tool_result({"ok": False, "error": "background_not_supported"}, spec=spec)
            if context is None:
                return normalize_tool_result({"ok": False, "error": "background_context_required"}, spec=spec)
            from pallas.product.llm.tools.background import start_background_tool

            queued = start_background_tool(
                tool_name=spec.name,
                context=context,
                arguments=dict(args),
                max_execution_ms=spec.max_execution_ms,
            )
            return normalize_tool_result({"ok": True, "result": queued}, spec=spec)
        dedupe_key = str(args.get(spec.idempotency_key) or "").strip() if spec.idempotency_key else ""
        cache_key = (
            spec.name,
            context.bot_id if context is not None else None,
            context.group_id if context is not None else None,
            context.user_id if context is not None else None,
            dedupe_key,
        )
        if dedupe_key and cache_key in _IDEMPOTENT_RESULTS:
            return _IDEMPOTENT_RESULTS[cache_key]
        try:
            current_spec = spec

            async def invoke(current_spec: LlmToolSpec = current_spec) -> Any:
                if current_spec.source == LlmToolSource.MCP:
                    from pallas.product.llm.tools.mcp_bootstrap import execute_mcp_tool_async

                    return await execute_mcp_tool_async(current_spec, args)
                result = current_spec.handler(args, context)
                return await result if inspect.isawaitable(result) else result

            timeout = max(1, int(spec.max_execution_ms)) / 1000 if spec.max_execution_ms > 0 else None
            result = await asyncio.wait_for(invoke(), timeout=timeout) if timeout is not None else await invoke()
            normalized = normalize_tool_result(result, spec=spec)
            if dedupe_key:
                _IDEMPOTENT_RESULTS[cache_key] = normalized
            return normalized
        except TimeoutError:
            return normalize_tool_result({"ok": False, "error": "tool_timeout"}, spec=spec)
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


def tool_metadata_for_chat(
    *,
    task: str | None = None,
    user_text: str = "",
    bot_id: int | None = None,
    group_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """写入 Bot 工具 metadata：tool_catalog + 兼容字段 tools_enabled / tool_schemas。"""
    from pallas.product.llm.task_metrics import record_bot_llm_task

    normalized = str(task or "").strip().lower()
    cfg = get_llm_config()
    activated_names = frozenset()
    if bot_id is not None and user_id is not None:
        from pallas.product.llm.tools.activation_cache import activated_tool_names

        activated_names = frozenset(activated_tool_names(bot_id, group_id, user_id))
    catalog = tool_catalog_for_chat(task=task, user_text=user_text, activated_names=activated_names)
    if catalog is None:
        # selective 开启且非 no-tool task：空目录 = 口语未命中硬域与软召回
        if (
            normalized not in _NO_TOOL_TASKS
            and cfg.llm_tools_enabled
            and cfg.llm_tools_selective
            and str(user_text or "").strip()
        ):
            record_bot_llm_task(normalized or "llm_chat", "selective_empty")
            if bool(getattr(cfg, "llm_tools_soft_recall_enabled", True)):
                record_bot_llm_task(normalized or "llm_chat", "soft_recall_empty")
        return {}
    source = str(catalog.selection.selection_source or "").strip().lower()
    if catalog.selection.inventory_intent:
        record_bot_llm_task(normalized or "llm_chat", "inventory_hit")
    if source.startswith("soft_recall"):
        record_bot_llm_task(normalized or "llm_chat", "soft_recall_hit")
    elif source.startswith("selective"):
        record_bot_llm_task(normalized or "llm_chat", "selective_hit")
    elif catalog.selection.selective_enabled and source not in {"inventory", "all"}:
        record_bot_llm_task(normalized or "llm_chat", "selective_hit")
    schemas = openai_schemas_from_catalog(catalog)
    payload: dict[str, Any] = {
        "tools_enabled": True,
        "tool_catalog": catalog.model_dump(mode="json"),
        "tool_schemas": schemas,
        "tool_schema_count": int(catalog.selection.schema_count),
        "selection_source": source or "all",
        "ask_before_call": bool(catalog.selection.ask_before_call),
        "missing_required_params": dict(catalog.selection.missing_required_params or {}),
        "soft_recall_confidence": int(catalog.selection.soft_recall_confidence or 0),
        "semantic_recall_confidence": int(catalog.selection.semantic_recall_confidence or 0),
        "semantic_recall_candidates": list(catalog.selection.semantic_recall_candidates or []),
        "activated_tools": sorted(activated_names),
        "inventory_intent": bool(catalog.selection.inventory_intent),
    }
    # 选择性命中 / 软召回材料齐全 / 盘点：首轮要求必须调工具，避免只口头答应。
    # 软召回缺参时不强制，便于自然追问。
    if catalog.selection.inventory_intent and catalog.tools:
        payload["tool_choice_prefer"] = "required"
    elif catalog.tools and not catalog.selection.ask_before_call:
        sources = {str(item.source or "") for item in catalog.tools}
        tool_names = {str(item.name or "") for item in catalog.tools}
        domains = {str(d) for item in catalog.tools for d in (item.domains or [])}
        prefer_plugin = bool(sources) and sources <= {LlmToolSource.PLUGIN_COMMAND.value}
        prefer_web = "web" in domains or bool(tool_names.intersection({"web.search", "web.fetch"}))
        if catalog.selection.selective_enabled and prefer_plugin:
            payload["tool_choice_prefer"] = "required"
        elif catalog.selection.selective_enabled and prefer_web:
            payload["tool_choice_prefer"] = "required"
        elif source.startswith("soft_recall") and prefer_plugin:
            # 与硬域同等：软召回已命中且参数可填时，禁止空口答应
            payload["tool_choice_prefer"] = "required"
    return payload


def build_tools_catalog_ui() -> dict[str, Any]:
    """WebUI 工具清单：全量可见 tool + 策略门闸 + 覆写字段。"""
    from pallas.product.llm.tools.metadata import iter_package_declared_llm_tools

    cfg = get_llm_config()
    kb = get_arknights_kb_config()
    ensure_tools_loaded()
    blacklist = {item.strip().lower() for item in cfg.llm_tools_blacklist if item.strip()}
    eligible_names = {spec.name for spec in iter_eligible_tool_specs()}
    overrides = load_tool_overrides()
    items: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for spec in iter_registered_tools():
        if not spec.visible_in_ui:
            continue
        entry = catalog_entry_for_spec(spec)
        override = overrides.get(spec.name) or {}
        disabled_reason: str | None = None
        if tool_override_disabled(spec.name):
            disabled_reason = "override_disabled"
        elif not cfg.llm_tools_enabled:
            disabled_reason = "tools_disabled"
        elif spec.name.lower() in blacklist or spec.domains.intersection(blacklist):
            disabled_reason = "blacklisted"
        elif "arknights" in spec.domains and not kb.arknights_kb_enabled:
            disabled_reason = "arknights_kb_disabled"
        declared_hints = sorted(str(h) for h in (spec.hints or frozenset()) if str(h).strip())
        effective_hints = sorted(effective_tool_hints(spec))
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
            "estimated_duration_ms": entry.estimated_duration_ms,
            "cost_hint": entry.cost_hint,
            "read_only": entry.read_only,
            "approval_required": entry.approval_required,
            "reversible": entry.reversible,
            "idempotency_key": entry.idempotency_key,
            "max_execution_ms": entry.max_execution_ms,
            "background_ok": entry.background_ok,
            "display_mode": entry.display_mode,
            "eligible": spec.name in eligible_names and disabled_reason is None,
            "disabled_reason": disabled_reason,
            "hints": declared_hints,
            "effective_hints": effective_hints,
            "visibility": effective_tool_visibility(spec),
            "declared_visibility": str(spec.visibility or "visible"),
            "override": {
                "description": str(override.get("description") or "") or None,
                "hints": list(override["hints"]) if isinstance(override.get("hints"), list) else None,
                "visibility": override.get("visibility"),
                "disabled": bool(override.get("disabled")) if "disabled" in override else None,
            },
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
        override = overrides.get(decl.name) or {}
        declared_hints = [str(h).strip() for h in (getattr(decl, "hints", None) or []) if str(h).strip()]
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
            "hints": declared_hints,
            "effective_hints": declared_hints,
            "visibility": str(getattr(decl, "visibility", "visible") or "visible"),
            "declared_visibility": str(getattr(decl, "visibility", "visible") or "visible"),
            "override": {
                "description": str(override.get("description") or "") or None,
                "hints": list(override["hints"]) if isinstance(override.get("hints"), list) else None,
                "visibility": override.get("visibility"),
                "disabled": bool(override.get("disabled")) if "disabled" in override else None,
            },
        })
        seen_names.add(decl.name)
    items.sort(key=operator.itemgetter("name"))
    from pallas.product.llm.tools.mcp_bootstrap import mcp_registration_snapshot

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
            "mcp": mcp_registration_snapshot(),
        },
        "overrides": overrides,
    }


def build_tools_ui_rows() -> list[dict[str, Any]]:
    return list(build_tools_catalog_ui().get("items") or [])
