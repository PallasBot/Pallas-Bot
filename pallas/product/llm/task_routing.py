from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .model_admin import fetch_local_routing_config
from .startup_probe import probe_ai_service_health

_CACHE_TTL_SEC = 15.0
_health_cache: dict[str, Any] = {}
_health_cache_at = 0.0
_local_routing_cache: dict[str, Any] = {}
_local_routing_cache_at = 0.0
_providers_cache: dict[str, Any] = {}
_providers_cache_at = 0.0


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


def serialize_task_route(spec: TaskRouteSpec) -> dict[str, Any]:
    payload = asdict(spec)
    payload["fallback_models"] = list(spec.fallback_models)
    return payload


def clear_task_route_cache() -> None:
    global _health_cache_at, _local_routing_cache_at, _providers_cache_at
    _health_cache.clear()
    _local_routing_cache.clear()
    _providers_cache.clear()
    _health_cache_at = 0.0
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


async def _cached_ai_health_payload() -> dict[str, Any]:
    global _health_cache_at
    now = time.monotonic()
    if _health_cache and now - _health_cache_at < _CACHE_TTL_SEC:
        return dict(_health_cache)
    result = await probe_ai_service_health(timeout_sec=2.0)
    body = result.get("body")
    payload = dict(body) if result.get("ok") and isinstance(body, dict) else {}
    _health_cache.clear()
    _health_cache.update(payload)
    _health_cache_at = now
    return payload


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
) -> tuple[str, ...]:
    routing = providers_payload.get("routing")
    if not isinstance(routing, dict):
        return ()
    chain_fallback = routing.get("chain_fallback")
    if not isinstance(chain_fallback, list):
        return ()
    out: list[str] = []
    for raw in chain_fallback:
        provider_id = str(raw or "").strip()
        if not provider_id or provider_id == primary_provider:
            continue
        model = _resolve_provider_task_model(providers_payload, provider_id, task)
        if model:
            out.append(model)
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

    health_payload = await _cached_ai_health_payload()
    llm_info = health_payload.get("llm") if isinstance(health_payload.get("llm"), dict) else {}
    provider_mode = str(llm_info.get("provider_mode") or "").strip() or None
    fallbacks = _fallback_models_from_payload(llm_info, normalized_task)

    routed_provider = _mapping_lookup(llm_info.get("task_routing"), normalized_task)
    if routed_provider:
        providers_payload = await _cached_providers_payload()
        resolved_model = _resolve_provider_task_model(providers_payload, routed_provider, normalized_task)
        if not resolved_model:
            resolved_model = _mapping_lookup(llm_info.get("local_task_models"), normalized_task)
        chain_fallbacks = _chain_fallback_models(
            providers_payload,
            task=normalized_task,
            primary_provider=routed_provider,
        )
        merged_fallbacks = chain_fallbacks or fallbacks
        return TaskRouteSpec(
            task=normalized_task,
            resolved_model=resolved_model,
            provider_hint=routed_provider,
            source="ai_health",
            fallback_models=merged_fallbacks,
        )

    local_model = _mapping_lookup(llm_info.get("local_task_models"), normalized_task)
    if local_model:
        return TaskRouteSpec(
            task=normalized_task,
            resolved_model=local_model,
            provider_hint=provider_mode,
            source="ai_health",
            fallback_models=fallbacks,
        )

    local_payload = await _cached_local_routing_payload()
    resolved = _route_from_local_config(normalized_task, local_payload)
    local_fallbacks = _fallback_models_from_payload(local_payload, normalized_task) or fallbacks
    if resolved:
        return TaskRouteSpec(
            task=normalized_task,
            resolved_model=resolved,
            provider_hint=provider_mode,
            source="config" if not fallbacks else "fallback",
            fallback_models=local_fallbacks,
        )
    if local_fallbacks:
        return TaskRouteSpec(
            task=normalized_task,
            resolved_model=local_fallbacks[0],
            provider_hint=provider_mode,
            source="fallback",
            fallback_models=local_fallbacks[1:],
        )
    return TaskRouteSpec(
        task=normalized_task,
        resolved_model=None,
        provider_hint=provider_mode,
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
