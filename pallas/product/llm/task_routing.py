from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .model_admin import fetch_local_routing_config

_CACHE_TTL_SEC = 15.0
_local_routing_cache: dict[str, Any] = {}
_local_routing_cache_at = 0.0
_providers_cache: dict[str, Any] = {}
_providers_cache_at = 0.0

HIGH_TIER_TASKS = frozenset({"llm_chat", "drunk", "repeater_polish"})
LOW_TIER_TASKS = frozenset({
    "repeater_select",
    "repeater_polish_lite",
    "repeater_fallback",
    "affect_refine",
    "turn_decision",
})


@dataclass(frozen=True)
class TaskRouteSpec:
    task: str
    resolved_model: str | None
    provider_hint: str | None
    source: Literal["config", "ai_health", "explicit", "fallback"]
    fallback_models: tuple[str, ...] = ()


def resolve_submit_task_name(task: str | None, mode: str | None = None) -> str:
    task_name = str(task or "").strip().lower()
    if task_name:
        return task_name
    if str(mode or "normal").strip().lower() == "drunk":
        return "drunk"
    return "llm_chat"


def task_route_tier(task: str) -> str:
    task_name = str(task or "").strip().lower()
    if task_name in HIGH_TIER_TASKS:
        return "high"
    if task_name in LOW_TIER_TASKS:
        return "low"
    return ""


def serialize_task_route(spec: TaskRouteSpec) -> dict[str, Any]:
    payload = asdict(spec)
    payload["fallback_models"] = list(spec.fallback_models)
    return payload


def clear_task_route_cache() -> None:
    global _local_routing_cache_at, _providers_cache_at
    _local_routing_cache.clear()
    _providers_cache.clear()
    _local_routing_cache_at = 0.0
    _providers_cache_at = 0.0


def _mapping_lookup(mapping: Any, task: str) -> str | None:
    if not isinstance(mapping, dict):
        return None
    value = str(mapping.get(task) or "").strip()
    return value or None


def _route_from_local_config(task: str, payload: dict[str, Any]) -> str | None:
    for key in ("task_models", "task_routing", "local_task_models"):
        resolved = _mapping_lookup(payload.get(key), task)
        if resolved:
            return resolved
    fallback = str(payload.get("llm_model") or payload.get("model") or "").strip()
    return fallback or None


async def _cached_local_routing_payload() -> dict[str, Any]:
    global _local_routing_cache_at
    now = time.monotonic()
    if _local_routing_cache and now - _local_routing_cache_at < _CACHE_TTL_SEC:
        return dict(_local_routing_cache)
    try:
        payload = await fetch_local_routing_config(timeout_sec=2.0)
    except Exception:
        payload = {}
    payload = dict(payload) if isinstance(payload, dict) else {}
    _local_routing_cache.clear()
    _local_routing_cache.update(payload)
    _local_routing_cache_at = now
    return payload


async def _cached_providers_payload() -> dict[str, Any]:
    global _providers_cache_at
    now = time.monotonic()
    if _providers_cache and now - _providers_cache_at < _CACHE_TTL_SEC:
        return dict(_providers_cache)
    try:
        from .model_admin import fetch_providers_config

        payload = await fetch_providers_config(timeout_sec=2.0)
    except Exception:
        payload = {}
    payload = dict(payload) if isinstance(payload, dict) else {}
    _providers_cache.clear()
    _providers_cache.update(payload)
    _providers_cache_at = now
    return payload


def _provider_row(providers_payload: dict[str, Any], provider_id: str) -> dict[str, Any] | None:
    rows = providers_payload.get("providers")
    if not isinstance(rows, list):
        return None
    for raw in rows:
        if isinstance(raw, dict) and str(raw.get("id") or "").strip() == provider_id:
            return raw
    return None


def _resolve_provider_task_model(providers_payload: dict[str, Any], provider_id: str, task: str) -> str | None:
    row = _provider_row(providers_payload, provider_id)
    if not row:
        return None
    task_models = row.get("task_models")
    if isinstance(task_models, dict):
        model = str(task_models.get(task) or "").strip()
        if model:
            return model
    default_model = str(row.get("default_model") or "").strip()
    return default_model or None


def _chain_fallback_models(
    providers_payload: dict[str, Any],
    *,
    task: str,
    primary_provider: str,
    primary_model: str | None = None,
) -> tuple[str, ...]:
    routing = providers_payload.get("routing")
    if not isinstance(routing, dict):
        return ()

    tier = task_route_tier(task)

    out: list[str] = []
    seen: set[str] = set()
    primary_model_norm = str(primary_model or "").strip()
    if primary_model_norm:
        seen.add(primary_model_norm)

    def add_model(model: str | None) -> None:
        name = str(model or "").strip()
        if not name or name in seen:
            return
        seen.add(name)
        out.append(name)

    # 全任务备用优先于高低档备用
    task_backups = routing.get("task_backups")
    task_backup_models = routing.get("task_backup_models")
    if isinstance(task_backups, dict):
        backup_provider = str(task_backups.get(task) or "").strip()
        backup_model = ""
        if isinstance(task_backup_models, dict):
            backup_model = str(task_backup_models.get(task) or "").strip()
        if backup_provider:
            if backup_model:
                add_model(backup_model)
            elif backup_provider != primary_provider:
                add_model(_resolve_provider_task_model(providers_payload, backup_provider, task))

    if tier:
        tier_backups = routing.get("tier_backups")
        tier_backup_models = routing.get("tier_backup_models")
        backup_provider = ""
        backup_model = ""
        if isinstance(tier_backups, dict):
            backup_provider = str(tier_backups.get(tier) or "").strip()
        if isinstance(tier_backup_models, dict):
            backup_model = str(tier_backup_models.get(tier) or "").strip()
        if backup_provider:
            if backup_model:
                add_model(backup_model)
            elif backup_provider != primary_provider:
                add_model(_resolve_provider_task_model(providers_payload, backup_provider, task))

    chain_fallback = routing.get("chain_fallback")
    if not isinstance(chain_fallback, list):
        return tuple(out)
    for raw in chain_fallback:
        provider_id = str(raw or "").strip()
        if not provider_id or provider_id == primary_provider:
            continue
        add_model(_resolve_provider_task_model(providers_payload, provider_id, task))
    return tuple(out)


def _fallback_models_from_payload(payload: dict[str, Any], task: str) -> tuple[str, ...]:
    chains = payload.get("task_fallback_chains")
    if isinstance(chains, dict):
        raw = chains.get(task)
        if isinstance(raw, list):
            out = [str(x).strip() for x in raw if str(x).strip()]
            if out:
                return tuple(out)
    fallback = payload.get("task_fallback") or payload.get("llm_model_fallback")
    if isinstance(fallback, dict):
        raw = fallback.get(task) or fallback.get("default")
        if isinstance(raw, list):
            return tuple(str(x).strip() for x in raw if str(x).strip())
        if isinstance(raw, str) and raw.strip():
            return (raw.strip(),)
    return ()


async def resolve_task_route(task: str, *, explicit_model: str | None = None) -> TaskRouteSpec:
    normalized_task = resolve_submit_task_name(task)
    explicit = str(explicit_model or "").strip()
    if explicit:
        return TaskRouteSpec(
            task=normalized_task,
            resolved_model=explicit,
            provider_hint=None,
            source="explicit",
            fallback_models=(),
        )

    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.providers_store import export_providers_for_api, resolve_endpoint_for_task

    cfg = get_llm_config()
    endpoint = resolve_endpoint_for_task(normalized_task)
    if endpoint is not None:
        providers_payload = export_providers_for_api()
        chain_fallbacks = _chain_fallback_models(
            providers_payload,
            task=normalized_task,
            primary_provider=endpoint.provider_id,
            primary_model=endpoint.model,
        )
        return TaskRouteSpec(
            task=normalized_task,
            resolved_model=endpoint.model,
            provider_hint=endpoint.provider_id,
            source="config",
            fallback_models=chain_fallbacks,
        )
    model = str(cfg.llm_model or "").strip() or None
    return TaskRouteSpec(
        task=normalized_task,
        resolved_model=model,
        provider_hint="bot_kernel",
        source="config",
        fallback_models=(),
    )


async def resolve_task_route_chain(task: str, *, explicit_model: str | None = None) -> list[TaskRouteSpec]:
    """显式 fallback 链：主模型失败时可依次尝试 fallback_models。"""
    primary = await resolve_task_route(task, explicit_model=explicit_model)
    chain = [primary]
    chain.extend(
        TaskRouteSpec(
            task=primary.task,
            resolved_model=model,
            provider_hint=primary.provider_hint,
            source="fallback",
            fallback_models=(),
        )
        for model in primary.fallback_models
    )
    return chain


_TASK_ROUTING_PREVIEW_TASKS: tuple[str, ...] = (
    "llm_chat",
    "repeater_fallback",
    "repeater_select",
    "repeater_polish",
    "turn_decision",
)


async def build_task_routing_preview() -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for task in _TASK_ROUTING_PREVIEW_TASKS:
        chain = await resolve_task_route_chain(task)
        preview[task] = {
            "chain": [serialize_task_route(item) for item in chain],
            "primary_model": chain[0].resolved_model if chain else None,
            "fallback_count": max(0, len(chain) - 1),
        }
    return preview
