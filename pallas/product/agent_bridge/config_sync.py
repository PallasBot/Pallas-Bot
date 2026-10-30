"""首次迁移共享人设与 Pallas 模型配置到 MaiBot 原生 TOML。

调用方只在实例已停机并持有 start/stop 锁时调用。完成迁移后 marker 仅表示
“已迁移”；MaiBot 原生模型配置随后完全由 MaiBot 管理。
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import tomlkit

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.product.llm import providers_store
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.knowledge.embedding_provider import (
    resolve_embedding_catalog_provider_id,
    resolve_embedding_provider_name,
    resolve_remote_embedding_model,
)
from pallas.product.llm.provider_client.auth import endpoint_api_keys
from pallas.product.llm.provider_client.mapping import apply_model_effort_to_payload
from pallas.product.llm.provider_client.urls import openai_api_root, resolve_request_method
from pallas.product.llm.providers_store import (
    provider_capabilities,
    provider_model_effort,
    provider_model_reasoning_effort_none_on_disable,
    provider_request_method,
    resolve_provider_api_keys,
    resolve_provider_base_url,
)
from pallas.product.llm.task_routing import task_route_tier
from pallas.product.persona.compile_persona_prompt import load_base_system_prompt
from pallas.product.persona.self_identity import extract_generic_self_aliases

CONFIG_SYNC_ENABLED_KEY = "MAIBOT_CONFIG_SYNC_ENABLED"
BOT_CONFIG_FILENAME = "bot_config.toml"
MODEL_CONFIG_FILENAME = "model_config.toml"
MARKER_FILENAME = ".pallas-managed.json"
BOT_CONFIG_VERSION = "8.15.47"
MODEL_CONFIG_VERSION = "1.17.24"
MANAGED_PREFIX = "pallas-import-"
MARKER_VERSION = 3
BACKUP_SUFFIX = ".pallas-backup"

# 目标侧 TaskConfig 键 -> Pallas 任务名。memory/learner/fast_model/emoji/vlm/voice
# 未明确映射，保持 MaiBot 原生 fallback 或手工配置。
LLM_TASK_SOURCES: dict[str, str] = {
    "replyer": "llm_chat",
    "planner": "llm_chat",
    "utils": "turn_decision",
}
_CLIENT_TYPES = {"chat_completions": "openai", "responses": "openai_responses"}
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_V2_PROVIDER_ALIAS = "pallas-managed"
_V2_ROUTE_ALIASES = {"pb-route-chat", "pb-route-decision"}
_V2_EMBEDDING_ALIAS = re.compile(r"pb-embedding-[0-9a-f]{24}")
_V3_WARNING_CODES = frozenset({
    "daily_limits_not_migrated",
    "non_cny_pricing_not_migrated",
    "unsupported_request_method",
    "local_embedding_not_migrated",
})


class ConfigSyncError(RuntimeError):
    """MaiBot 实例配置无法在目标侧安全同步。"""


def config_sync_enabled() -> bool:
    """首次迁移默认开启；显式 false 可关闭，非法值不回显。"""
    raw = repo_env_raw_value(CONFIG_SYNC_ENABLED_KEY)
    text = str(raw or "").strip().lower()
    if not text:
        return True
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ConfigSyncError(f"{CONFIG_SYNC_ENABLED_KEY} must be a boolean")


def _load_persona_text() -> str:
    return load_base_system_prompt()


def _load_identity_aliases() -> list[str]:
    return list(extract_generic_self_aliases())


def _load_embedding_source(
    cfg: Any | None = None,
    document: dict[str, Any] | None = None,
    *,
    store_exists: bool = False,
) -> dict[str, Any] | None:
    cfg = cfg or get_llm_config()
    provider_kind = resolve_embedding_provider_name(cfg)
    if provider_kind == "local":
        return {"unsupported": "local_embedding_not_migrated"}
    if provider_kind != "openai":
        return None
    model = str(resolve_remote_embedding_model(cfg) or "").strip()
    if not model:
        return None
    rows = {str(row.get("id") or ""): row for row in (document or {}).get("providers", []) if isinstance(row, dict)}
    source_id = resolve_embedding_catalog_provider_id(cfg)
    source = rows.get(source_id)
    base_url = resolve_provider_base_url(source) if source else ""
    keys = resolve_provider_api_keys(source) if source else []
    if not base_url or not keys:
        endpoint = None
        if store_exists:
            candidates = providers_store.resolve_endpoint_candidates_for_task("llm_chat")
            endpoint = candidates[0] if candidates else None
        chat_url = str(getattr(endpoint, "base_url", "") or getattr(cfg, "llm_base_url", "") or "").strip()
        chat_keys = endpoint_api_keys(
            endpoint or SimpleNamespace(api_key="", api_keys=()),
            fallback=str(getattr(cfg, "llm_api_key", "") or ""),
        )
        if not base_url:
            base_url = chat_url
            if not source_id and endpoint is not None:
                source_id = str(getattr(endpoint, "provider_id", "") or "")
        if not keys:
            keys = chat_keys
    explicit_base = str(
        getattr(cfg, "llm_embedding_base_url", "") or repo_env_raw_value("LLM_EMBEDDING_BASE_URL") or ""
    ).strip()
    explicit_key = str(
        getattr(cfg, "llm_embedding_api_key", "") or repo_env_raw_value("LLM_EMBEDDING_API_KEY") or ""
    ).strip()
    if explicit_key:
        keys = [explicit_key]
    if explicit_base:
        base_url = explicit_base
        if not source_id:
            source_id = "manual"
    if not base_url:
        return None
    return {"base_url": str(base_url).strip(), "model": model, "provider_id": str(source_id or ""), "api_keys": keys}


def _configured_route_ids(document: dict[str, Any], task: str) -> set[str]:
    routing = document.get("routing") if isinstance(document.get("routing"), dict) else {}
    ids: set[str] = set()
    tasks = routing.get("tasks") if isinstance(routing.get("tasks"), dict) else {}
    backups = routing.get("task_backups") if isinstance(routing.get("task_backups"), dict) else {}

    def add(value: object) -> None:
        text = str(value or "").strip()
        if text:
            ids.add(text)

    add(tasks.get(task))
    add(backups.get(task))
    tier = task_route_tier(task)
    tier_backups = routing.get("tier_backups") if isinstance(routing.get("tier_backups"), dict) else {}
    if tier:
        add(tier_backups.get(tier))
    chain = routing.get("chain_fallback") if isinstance(routing.get("chain_fallback"), list) else []
    for provider_id in chain:
        add(provider_id)
    return ids


def _model_extra_params(row: dict[str, Any] | None, model: str, method: str) -> dict[str, Any]:
    effort = provider_model_effort(row, model)
    payload: dict[str, Any] = {"model": model}
    apply_model_effort_to_payload(
        payload,
        {"model_effort": effort},
        model=model,
        request_method=method,
        reasoning_effort_none_on_disable=provider_model_reasoning_effort_none_on_disable(row, model),
    )
    return {key: value for key, value in payload.items() if key != "model"}


def _pricing_fields(row: dict[str, Any], model: str, currency: str) -> dict[str, Any]:
    if currency != "CNY":
        return {}
    pricing = row.get("model_pricing") if isinstance(row.get("model_pricing"), dict) else {}
    model_price = pricing.get(model) if isinstance(pricing.get(model), dict) else {}
    fields = {key: model_price[key] for key in ("price_in", "price_out", "cache_price_in") if key in model_price}
    if fields.get("cache_price_in", 0):
        fields["cache"] = True
    return fields


def _model_names(row: dict[str, Any]) -> list[str]:
    names: list[str] = []
    models = row.get("models") if isinstance(row.get("models"), list) else []
    for item in models:
        name = str(item.get("name") or "").strip() if isinstance(item, dict) else ""
        if name and name not in names:
            names.append(name)
    for name in [
        row.get("default_model"),
        *(row.get("task_models", {}).values() if isinstance(row.get("task_models"), dict) else []),
    ]:
        text = str(name or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def _build_plan(model_plain: dict[str, Any]) -> dict[str, Any]:
    cfg = get_llm_config()
    store_path = providers_store.providers_store_path()
    if store_path.is_file():
        try:
            raw_document = json.loads(store_path.read_text(encoding="utf-8"))
            if not isinstance(raw_document, dict) or not isinstance(raw_document.get("providers", []), list):
                raise ValueError
            document = providers_store.load_providers_document(refresh=True)
        except Exception:
            raise ConfigSyncError("Pallas provider catalog is unavailable") from None
        if not isinstance(document, dict):
            raise ConfigSyncError("Pallas provider catalog is unavailable")
    else:
        document = {"providers": [], "routing": {}}
    source_rows = [row for row in document.get("providers", []) if isinstance(row, dict)]
    rows_by_id = {str(row.get("id") or "").strip(): row for row in source_rows}
    if len(rows_by_id) != len(source_rows):
        raise ConfigSyncError("Pallas provider catalog contains duplicate identifiers")

    warnings: set[str] = set()
    routing = document.get("routing") if isinstance(document.get("routing"), dict) else {}
    currency = str(routing.get("cost_currency") or "").strip().upper()
    if any(
        int(row.get("daily_tokens_cap") or 0) > 0 or float(row.get("daily_cost_cap") or 0) > 0 for row in source_rows
    ):
        warnings.add("daily_limits_not_migrated")
    if (
        int(getattr(cfg, "llm_chat_daily_calls_limit", 0) or 0) > 0
        or int(getattr(cfg, "llm_chat_daily_tokens_limit", 0) or 0) > 0
    ):
        warnings.add("daily_limits_not_migrated")
    if currency != "CNY" and any(row.get("model_pricing") for row in source_rows):
        warnings.add("non_cny_pricing_not_migrated")

    native_existing_providers = {str(row.get("name") or "") for row in model_plain.get("api_providers", [])}
    native_existing_models = {str(row.get("name") or "") for row in model_plain.get("models", [])}
    providers: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {}
    provider_names: dict[tuple[str, str, str, str], str] = {}
    model_names: dict[tuple[str, str, str, str, str], str] = {}
    provider_order = {str(row.get("id") or "").strip(): index + 1 for index, row in enumerate(source_rows)}
    global_key = str(getattr(cfg, "llm_api_key", "") or "").strip()
    endpoint_fallback = global_key

    def add_provider(provider_id: str, key_index: int, base_url: str, api_key: str, client_type: str) -> str:
        identity = (provider_id, api_key, base_url, client_type)
        if identity in provider_names:
            return provider_names[identity]
        ordinal = provider_order.get(provider_id, len(provider_order) + 1)
        name = f"{MANAGED_PREFIX}provider-{ordinal}-key-{key_index + 1}"
        suffix = 2
        while name in native_existing_providers or name in providers:
            name = f"{MANAGED_PREFIX}provider-{ordinal}-key-{key_index + 1}-{suffix}"
            suffix += 1
        providers[name] = {
            "name": name,
            "base_url": openai_api_root(base_url),
            "api_key": api_key,
            "client_type": client_type,
            "auth_type": "bearer" if api_key else "none",
        }
        provider_names[identity] = name
        return name

    def add_model(
        provider_id: str,
        model: str,
        api_key: str,
        *,
        row: dict[str, Any] | None,
        base_url: str,
        method: str,
        client_type: str,
        key_index: int,
        model_index: int,
        model_type: str = "llm",
    ) -> str:
        key = (provider_id, model, api_key, model_type, base_url)
        if key in model_names:
            return model_names[key]
        provider_name = add_provider(provider_id, key_index, base_url, api_key, client_type)
        ordinal = provider_order.get(provider_id, len(provider_order) + 1)
        name = f"{MANAGED_PREFIX}model-{ordinal}-{model_index + 1}-key-{key_index + 1}"
        suffix = 2
        while name in native_existing_models or name in models:
            name = f"{MANAGED_PREFIX}model-{ordinal}-{model_index + 1}-key-{key_index + 1}-{suffix}"
            suffix += 1
        capabilities = provider_capabilities(row, model)
        fields: dict[str, Any] = {
            "visual": "image" in capabilities,
            "force_stream_mode": provider_id == "cpa",
            "extra_params": _model_extra_params(row, model, method) if model_type == "llm" else {},
        }
        if model_type == "llm" and row is not None:
            fields.update(_pricing_fields(row, model, currency))
        models[name] = {
            "name": name,
            "model_identifier": model,
            "model_type": model_type,
            "api_provider": provider_name,
            **fields,
        }
        model_names[key] = name
        return name

    source_model_names: dict[str, list[str]] = {}
    for row in source_rows:
        provider_id = str(row.get("id") or "").strip()
        base_url = resolve_provider_base_url(row)
        method = resolve_request_method(provider_request_method(row), base_url)
        client_type = _CLIENT_TYPES.get(method)
        if client_type is None:
            warnings.add("unsupported_request_method")
            continue
        if not base_url:
            continue
        keys = resolve_provider_api_keys(row)
        if not keys:
            keys = endpoint_api_keys(SimpleNamespace(api_key="", api_keys=()), fallback=global_key)
        if not keys:
            keys = [""]
        names = _model_names(row)
        source_model_names[provider_id] = names
        for model_index, model in enumerate(names):
            for key_index, api_key in enumerate(keys):
                add_model(
                    provider_id,
                    model,
                    api_key,
                    row=row,
                    base_url=base_url,
                    method=method,
                    client_type=client_type,
                    key_index=key_index,
                    model_index=model_index,
                )

    def endpoint_candidates(task: str) -> list[Any]:
        allowed = _configured_route_ids(document, task)
        if not store_path.is_file():
            return []
        resolved = providers_store.resolve_endpoint_candidates_for_task(task)
        if not allowed:
            return [
                endpoint
                for endpoint in resolved
                if str(getattr(endpoint, "provider_id", "") or "").strip() in rows_by_id
            ]
        return [
            endpoint
            for endpoint in resolved
            if str(getattr(endpoint, "provider_id", "") or "").strip() in allowed
            and str(getattr(endpoint, "provider_id", "") or "").strip() in rows_by_id
        ]

    def build_task_route(task: str) -> list[str]:
        names: list[str] = []
        for endpoint in endpoint_candidates(task):
            provider_id = str(getattr(endpoint, "provider_id", "") or "").strip()
            row = rows_by_id[provider_id]
            base_url = str(getattr(endpoint, "base_url", "") or resolve_provider_base_url(row)).strip()
            method = resolve_request_method(provider_request_method(row), base_url)
            client_type = _CLIENT_TYPES.get(method)
            if client_type is None:
                warnings.add("unsupported_request_method")
                continue
            model = str(getattr(endpoint, "model", "") or "").strip()
            if not model:
                continue
            keys = endpoint_api_keys(endpoint, fallback=endpoint_fallback)
            if not keys:
                keys = [""]
            source_names = source_model_names.get(provider_id, [])
            model_index = source_names.index(model) if model in source_names else len(source_names)
            for key_index, api_key in enumerate(keys):
                name = add_model(
                    provider_id,
                    model,
                    api_key,
                    row=row,
                    base_url=base_url,
                    method=method,
                    client_type=client_type,
                    key_index=key_index,
                    model_index=model_index,
                )
                if name not in names:
                    names.append(name)
        return names

    tasks = {name: build_task_route(source) for name, source in LLM_TASK_SOURCES.items()}
    legacy_url = str(getattr(cfg, "llm_base_url", "") or "").strip()
    legacy_model = str(getattr(cfg, "llm_model", "") or "").strip()
    legacy_method = resolve_request_method("chat_completions", legacy_url) if legacy_url else ""
    legacy_client = _CLIENT_TYPES.get(legacy_method)
    if legacy_url and legacy_model and legacy_client:
        legacy_keys = endpoint_api_keys(SimpleNamespace(api_key=getattr(cfg, "llm_api_key", ""), api_keys=()))
        legacy_route = [
            add_model(
                "legacy",
                legacy_model,
                key,
                row=None,
                base_url=legacy_url,
                method=legacy_method,
                client_type=legacy_client,
                key_index=index,
                model_index=0,
            )
            for index, key in enumerate(legacy_keys)
        ]
        for task, names in tasks.items():
            if not names:
                tasks[task] = legacy_route
    elif legacy_url and legacy_model:
        warnings.add("unsupported_request_method")

    embedding = _load_embedding_source(cfg, document, store_exists=store_path.is_file())
    if embedding and embedding.get("unsupported"):
        warnings.add(str(embedding["unsupported"]))
    elif embedding:
        base_url = str(embedding["base_url"])
        model = str(embedding["model"])
        source_id = str(embedding.get("provider_id") or "embedding") or "embedding"
        keys = [str(key or "").strip() for key in embedding.get("api_keys", [])] or [""]
        embeddings: list[str] = []
        for key_index, api_key in enumerate(keys):
            name = add_model(
                source_id,
                model,
                api_key,
                row=None,
                base_url=base_url,
                method="chat_completions",
                client_type="openai",
                key_index=key_index,
                model_index=0,
                model_type="embedding",
            )
            embeddings.append(name)
        tasks["embedding"] = embeddings

    aliases = [alias for alias in _load_identity_aliases() if str(alias).strip()]
    return {
        "persona": _load_persona_text(),
        "nickname": aliases[0] if aliases else "牛牛",
        "alias_names": aliases,
        "providers": providers,
        "models": models,
        "tasks": tasks,
        "warnings": sorted(warnings),
        "document": document,
    }


def _toml_value(value: Any) -> Any:
    if isinstance(value, dict):
        table = tomlkit.inline_table()
        for key, item in value.items():
            table[key] = _toml_value(item)
        return table
    if isinstance(value, list):
        array = tomlkit.array()
        for item in value:
            array.append(_toml_value(item))
        return array
    return value


def _to_table(entry: dict[str, Any]) -> Any:
    table = tomlkit.table()
    for key, value in entry.items():
        table[key] = _toml_value(value)
    return table


def _render_bot(bot_text: str, plan: dict[str, Any]) -> str:
    doc = tomlkit.parse(bot_text)
    for section in ("bot", "personality"):
        if not isinstance(doc.get(section), dict):
            doc[section] = tomlkit.table()
    doc["bot"]["nickname"] = plan["nickname"]
    doc["bot"]["alias_names"] = _toml_value(list(plan["alias_names"]))
    doc["personality"]["personality"] = plan["persona"]
    return tomlkit.dumps(doc)


def _verify_v2_aliases(model_plain: dict[str, Any], marker: dict[str, Any]) -> set[str]:
    provider_names = marker.get("provider_names", [])
    model_names = marker.get("model_names", [])
    task_keys = marker.get("task_keys", [])
    embedding_names = [name for name in model_names if _V2_EMBEDDING_ALIAS.fullmatch(name)]
    expected_models = _V2_ROUTE_ALIASES | set(embedding_names)
    expected_tasks = set(LLM_TASK_SOURCES) | ({"embedding"} if embedding_names else set())
    if (
        provider_names != [_V2_PROVIDER_ALIAS]
        or set(model_names) != expected_models
        or set(task_keys) != expected_tasks
    ):
        raise ConfigSyncError("managed alias marker conflicts with native configuration")
    providers = {row.get("name"): row for row in _rows(model_plain, "api_providers", MODEL_CONFIG_FILENAME)}
    models = {row.get("name"): row for row in _rows(model_plain, "models", MODEL_CONFIG_FILENAME)}
    tasks = _table(model_plain, "model_task_config", MODEL_CONFIG_FILENAME)
    provider = providers.get(_V2_PROVIDER_ALIAS)
    provider_fields = {
        "base_url": "http://pallas-provider.invalid",
        "api_key": "",
        "client_type": "pallas-managed",
        "auth_type": "none",
        "max_retry": 1,
        "timeout": 60,
    }
    if not isinstance(provider, dict) or any(provider.get(key) != value for key, value in provider_fields.items()):
        raise ConfigSyncError("managed alias marker conflicts with native configuration")
    for name in expected_models:
        row = models.get(name)
        expected_type = "embedding" if name in embedding_names else "llm"
        if (
            not isinstance(row, dict)
            or row.get("model_identifier") != name
            or row.get("model_type") != expected_type
            or row.get("api_provider") != _V2_PROVIDER_ALIAS
            or row.get("visual") is not False
            or row.get("force_stream_mode") is not False
            or row.get("extra_params") != {}
        ):
            raise ConfigSyncError("managed alias marker conflicts with native configuration")
    expected_task_models = {
        "replyer": ["pb-route-chat"],
        "planner": ["pb-route-chat"],
        "utils": ["pb-route-decision"],
    }
    if embedding_names:
        expected_task_models["embedding"] = embedding_names
    for key in expected_tasks:
        config = tasks.get(key)
        if not isinstance(config, dict) or config.get("model_list") != expected_task_models[key]:
            raise ConfigSyncError("managed alias marker conflicts with native configuration")
    managed_aliases = expected_models
    if any(
        row.get("name") not in managed_aliases and row.get("api_provider") == _V2_PROVIDER_ALIAS
        for row in models.values()
    ):
        raise ConfigSyncError("managed alias marker conflicts with native configuration")
    for key, config in tasks.items():
        if key in expected_tasks or not isinstance(config, dict):
            continue
        if set(config.get("model_list") or []) & managed_aliases:
            raise ConfigSyncError("managed alias marker conflicts with native configuration")
    return managed_aliases


def _reject_unmarked_proxy_aliases(model_plain: dict[str, Any]) -> None:
    providers = _rows(model_plain, "api_providers", MODEL_CONFIG_FILENAME)
    models = _rows(model_plain, "models", MODEL_CONFIG_FILENAME)
    if any(row.get("name") == _V2_PROVIDER_ALIAS or row.get("client_type") == "pallas-managed" for row in providers):
        raise ConfigSyncError("unmarked managed alias conflicts with native configuration")
    if any(
        row.get("name") in _V2_ROUTE_ALIASES or _V2_EMBEDDING_ALIAS.fullmatch(str(row.get("name") or ""))
        for row in models
    ):
        raise ConfigSyncError("unmarked managed alias conflicts with native configuration")


def _render_model(
    model_text: str,
    model_plain: dict[str, Any],
    plan: dict[str, Any],
    *,
    legacy_aliases: set[str] | None = None,
) -> str:
    doc = tomlkit.parse(model_text)
    models_aot = doc.get("models")
    if not isinstance(models_aot, list):
        models_aot = tomlkit.aot()
        doc["models"] = models_aot
    providers_aot = doc.get("api_providers")
    if not isinstance(providers_aot, list):
        providers_aot = tomlkit.aot()
        doc["api_providers"] = providers_aot

    aliases = legacy_aliases or set()
    if aliases:
        for index in reversed(range(len(models_aot))):
            if str(models_aot[index].get("name") or "") in aliases:
                del models_aot[index]
        for index in reversed(range(len(providers_aot))):
            if str(providers_aot[index].get("name") or "") == _V2_PROVIDER_ALIAS:
                del providers_aot[index]

    for entry in plan["providers"].values():
        providers_aot.append(_to_table(entry))
    for entry in plan["models"].values():
        models_aot.append(_to_table(entry))

    mtc = doc.get("model_task_config")
    if not isinstance(mtc, dict):
        mtc = tomlkit.table()
        doc["model_task_config"] = mtc
    for key, names in plan["tasks"].items():
        sub = mtc.get(key)
        if not isinstance(sub, dict):
            sub = tomlkit.table()
            mtc[key] = sub
        current = [str(name) for name in (sub.get("model_list") or [])]
        replacing_alias = bool(set(current) & aliases)
        replacing_default = _is_default_placeholder_route(key, current, model_plain)
        if current and not replacing_alias and not replacing_default:
            continue
        if names or replacing_alias or replacing_default:
            sub["model_list"] = _toml_value(names)
            if names:
                sub["selection_strategy"] = "sequential"
    return tomlkit.dumps(doc)


def _parse_toml(text: str, filename: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigSyncError(f"{filename} is not valid TOML") from exc
    if not isinstance(data, dict):
        raise ConfigSyncError(f"{filename} must contain a TOML table")
    return data


def _check_inner_version(plain: dict[str, Any], expected: str, filename: str) -> None:
    inner = plain.get("inner")
    version = inner.get("version") if isinstance(inner, dict) else None
    if version != expected:
        raise ConfigSyncError(f"{filename} has an unexpected inner version")


def _rows(plain: dict[str, Any], key: str, filename: str) -> list[dict[str, Any]]:
    value = plain.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ConfigSyncError(f"{filename} has an invalid {key} structure")
    return value


def _table(plain: dict[str, Any], key: str, filename: str) -> dict[str, Any]:
    value = plain.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigSyncError(f"{filename} has an invalid {key} structure")
    return value


def _check_structure(bot_plain: dict[str, Any], model_plain: dict[str, Any]) -> None:
    for key in ("bot", "personality"):
        _table(bot_plain, key, BOT_CONFIG_FILENAME)
    _rows(model_plain, "api_providers", MODEL_CONFIG_FILENAME)
    _rows(model_plain, "models", MODEL_CONFIG_FILENAME)
    mtc = _table(model_plain, "model_task_config", MODEL_CONFIG_FILENAME)
    for key, value in mtc.items():
        if value is not None and not isinstance(value, dict):
            raise ConfigSyncError(f"model_task_config.{key} must be a table")


_NATIVE_TASKS = frozenset({
    "replyer",
    "planner",
    "memory",
    "utils",
    "learner",
    "fast_model",
    "emoji",
    "vlm",
    "voice",
    "embedding",
    "image_embedding",
})
_CORE_TASKS = ("planner", "replyer", "utils")
_PLACEHOLDER_API_KEYS = frozenset({"your-api-key"})
_DEFAULT_CORE_ROUTES = {
    "replyer": ("deepseek-v4-pro-think", "deepseek-v4-pro-nonthink"),
    "planner": ("deepseek-v4-flash",),
    "utils": ("deepseek-v4-flash",),
}
_DEFAULT_CORE_MODELS = {
    "deepseek-v4-pro-think": (
        "deepseek-v4-pro",
        {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
    ),
    "deepseek-v4-pro-nonthink": ("deepseek-v4-pro", {"thinking": {"type": "disabled"}}),
    "deepseek-v4-flash": ("deepseek-v4-flash", {"thinking": {"type": "disabled"}}),
}


def _is_default_placeholder_route(task: str, names: list[str], model_plain: dict[str, Any]) -> bool:
    if tuple(names) != _DEFAULT_CORE_ROUTES.get(task):
        return False
    providers = {row.get("name"): row for row in _rows(model_plain, "api_providers", MODEL_CONFIG_FILENAME)}
    models = {row.get("name"): row for row in _rows(model_plain, "models", MODEL_CONFIG_FILENAME)}
    provider = providers.get("DeepSeek", {})
    if (
        provider.get("base_url") != "https://api.deepseek.com"
        or str(provider.get("api_key") or "").strip().lower() not in _PLACEHOLDER_API_KEYS
        or provider.get("client_type") != "openai"
        or provider.get("auth_type") != "bearer"
    ):
        return False
    return all(
        (model := models.get(name)) is not None
        and model.get("model_identifier") == _DEFAULT_CORE_MODELS[name][0]
        and model.get("model_type") == "llm"
        and model.get("api_provider") == "DeepSeek"
        and model.get("extra_params") == _DEFAULT_CORE_MODELS[name][1]
        for name in names
    )


def _native_config_reasons(model_plain: dict[str, Any], *, require_core: bool) -> list[str]:
    reasons: list[str] = []
    providers = _rows(model_plain, "api_providers", MODEL_CONFIG_FILENAME)
    models = _rows(model_plain, "models", MODEL_CONFIG_FILENAME)
    tasks = _table(model_plain, "model_task_config", MODEL_CONFIG_FILENAME)
    provider_names = [str(row.get("name") or "") for row in providers]
    model_names = [str(row.get("name") or "") for row in models]
    if not all(provider_names) or len(provider_names) != len(set(provider_names)):
        reasons.append("invalid_provider_table")
    if not all(model_names) or len(model_names) != len(set(model_names)):
        reasons.append("invalid_model_table")
    providers_by_name = {str(row.get("name") or ""): row for row in providers}
    models_by_name = {str(row.get("name") or ""): row for row in models}
    for row in providers:
        auth_type = str(row.get("auth_type") or "bearer")
        client_type = row.get("client_type", "openai")
        if not isinstance(client_type, str) or not client_type.strip():
            reasons.append("invalid_provider_client_type")
            client_type = ""
        if not row.get("name") or (client_type != "gemini" and not row.get("base_url")):
            reasons.append("invalid_provider_config")
        if auth_type != "none" and not str(row.get("api_key") or ""):
            reasons.append("invalid_provider_auth")
    for row in models:
        model_type = str(row.get("model_type") or "")
        if (
            not row.get("name")
            or not row.get("model_identifier")
            or model_type not in {"llm", "embedding", "image_embedding"}
        ):
            reasons.append("invalid_model_config")
        if str(row.get("api_provider") or "") not in providers_by_name:
            reasons.append("undefined_provider_reference")
    for task in _NATIVE_TASKS:
        config = tasks.get(task)
        if config is None:
            if require_core and task in _CORE_TASKS:
                reasons.append("core_task_model_missing")
            continue
        if not isinstance(config, dict):
            reasons.append("invalid_task_config")
            continue
        model_list = config.get("model_list", [])
        if not isinstance(model_list, list):
            reasons.append("invalid_task_config")
            continue
        if require_core and task in _CORE_TASKS and not model_list:
            reasons.append("core_task_model_missing")
        for name in model_list:
            model = models_by_name.get(str(name))
            if model is None:
                reasons.append("undefined_model_reference")
                continue
            model_type = str(model.get("model_type") or "")
            if task in {"embedding", "image_embedding"}:
                valid_type = model_type in {"embedding", "image_embedding"}
            else:
                valid_type = model_type == "llm"
            if not valid_type:
                reasons.append("invalid_task_model_type")
            provider = providers_by_name.get(str(model.get("api_provider") or ""), {})
            api_key = str(provider.get("api_key") or "").strip().lower()
            if api_key in _PLACEHOLDER_API_KEYS:
                reasons.append("placeholder_provider_key")
    return list(dict.fromkeys(reasons))


def _validate_rendered(bot_plain: dict[str, Any], model_plain: dict[str, Any]) -> None:
    _check_inner_version(bot_plain, BOT_CONFIG_VERSION, BOT_CONFIG_FILENAME)
    _check_inner_version(model_plain, MODEL_CONFIG_VERSION, MODEL_CONFIG_FILENAME)
    _check_structure(bot_plain, model_plain)
    reasons = _native_config_reasons(model_plain, require_core=True)
    if reasons:
        raise ConfigSyncError(f"rendered native model configuration is invalid: {', '.join(reasons)}")


def _ensure_within(instance_dir: Path, config_dir: Path) -> None:
    if config_dir.is_symlink():
        raise ConfigSyncError("instance config directory must not be a symlink")
    root = instance_dir.resolve()
    resolved = config_dir.resolve()
    if resolved != root and root not in resolved.parents:
        raise ConfigSyncError("instance config directory escapes the instance root")


def _ensure_plain_file(path: Path) -> None:
    if path.is_symlink():
        raise ConfigSyncError(f"refusing to write through a symlink: {path.name}")
    if not path.is_file():
        raise ConfigSyncError(f"required instance file is missing: {path.name}")


def _write_bytes_0600(path: Path, data: bytes, mode: int) -> None:
    """mkstemp + fchmod + rename；rename 后不再做可能失败的操作（mode 随 inode 保留）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp).replace(path)
    except BaseException:
        try:
            Path(tmp).unlink()
        except OSError:
            pass
        raise


def _write_text_0600(path: Path, text: str) -> None:
    _write_bytes_0600(path, text.encode("utf-8"), 0o600)


def _read_marker(marker_path: Path) -> dict[str, Any] | None:
    if marker_path.is_symlink():
        raise ConfigSyncError("managed marker must not be a symlink")
    if not marker_path.is_file():
        return None
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigSyncError("managed marker is unreadable") from exc
    if not isinstance(data, dict) or type(data.get("version")) is not int:
        raise ConfigSyncError("managed marker has an unsupported schema")
    version = data["version"]
    if version not in {1, 2, MARKER_VERSION}:
        raise ConfigSyncError("managed marker has an unsupported schema")
    if version == MARKER_VERSION:
        warnings = data.get("warnings", [])
        if (
            data.get("bot_config_version") != BOT_CONFIG_VERSION
            or data.get("model_config_version") != MODEL_CONFIG_VERSION
            or not isinstance(data.get("migrated_at"), str)
            or not isinstance(warnings, list)
            or not all(isinstance(item, str) for item in warnings)
            or any(item not in _V3_WARNING_CODES for item in warnings)
        ):
            raise ConfigSyncError("managed marker has an unsupported schema")
        return data
    if (
        data.get("bot_config_version") != BOT_CONFIG_VERSION
        or data.get("model_config_version") != MODEL_CONFIG_VERSION
        or not isinstance(data.get("digest"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", data["digest"])
        or not isinstance(data.get("updated_at"), str)
        or any(
            not isinstance(data.get(key), list) or not all(isinstance(name, str) for name in data[key])
            for key in ("provider_names", "model_names", "task_keys")
        )
    ):
        raise ConfigSyncError("managed marker has an unsupported schema")
    if version == 1 and (
        "budget_policy" in data
        or not data["provider_names"]
        or not data["model_names"]
        or len(set(data["provider_names"])) != len(data["provider_names"])
        or len(set(data["model_names"])) != len(data["model_names"])
        or any(not name.startswith("pallas-") or name == _V2_PROVIDER_ALIAS for name in data["provider_names"])
        or any(
            not name.startswith("pallas-") or name.startswith(("pb-route-", "pb-embedding-"))
            for name in data["model_names"]
        )
        or frozenset(data["task_keys"])
        not in {frozenset(LLM_TASK_SOURCES), frozenset(LLM_TASK_SOURCES) | {"embedding"}}
    ):
        raise ConfigSyncError("managed marker has an unsupported schema")
    if version == 2 and data.get("budget_policy") != "native-cycle+pallas-request-v1":
        raise ConfigSyncError("managed marker has an unsupported schema")
    return data


def config_migration_completed(instance_dir: Path) -> bool:
    """Return whether the instance has a valid v3 migration marker."""
    base = Path(instance_dir)
    config_dir = base / "config"
    _ensure_within(base, config_dir)
    marker = _read_marker(config_dir / MARKER_FILENAME)
    return marker is not None and marker["version"] == MARKER_VERSION


def _marker_text(warnings: list[str] | None = None) -> str:
    payload = {
        "version": MARKER_VERSION,
        "bot_config_version": BOT_CONFIG_VERSION,
        "model_config_version": MODEL_CONFIG_VERSION,
        "migrated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "warnings": sorted(set(warnings or [])),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def _check_backup_safety(path: Path) -> Path:
    backup = _backup_path(path)
    if backup.is_symlink():
        raise ConfigSyncError(f"refusing to write through a symlink backup: {backup.name}")
    if backup.exists() and not backup.is_file():
        raise ConfigSyncError(f"backup path is not a regular file: {backup.name}")
    if backup.is_file() and stat.S_IMODE(backup.stat().st_mode) & 0o077:
        raise ConfigSyncError(f"existing backup has unsafe permissions: {backup.name}")
    return backup


def _commit(
    bot_path: Path,
    model_path: Path,
    marker_path: Path,
    bot_text: str | None,
    model_text: str | None,
    marker_text: str,
    *,
    first_takeover: bool,
) -> None:
    config_paths = (bot_path, model_path)
    snapshots = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in config_paths}
    if marker_path.is_file() and not marker_path.is_symlink():
        snapshots[marker_path] = (marker_path.read_bytes(), stat.S_IMODE(marker_path.stat().st_mode))
    backups = {path: _check_backup_safety(path) for path in (bot_path, model_path)}
    if first_takeover:
        for path, backup in backups.items():
            if backup.is_file() and backup.read_bytes() != snapshots[path][0]:
                raise ConfigSyncError(f"existing backup differs from current config: {backup.name}")
        for path, backup in backups.items():
            if not backup.is_file():
                _write_bytes_0600(backup, snapshots[path][0], 0o600)
    written: list[Path] = []
    try:
        updates = [(path, text) for path, text in ((bot_path, bot_text), (model_path, model_text)) if text is not None]
        updates.append((marker_path, marker_text))
        for path, text in updates:
            _write_text_0600(path, text)
            written.append(path)
    except BaseException as exc:
        restore_ok = True
        for path in written:
            if path not in snapshots:
                continue
            data, mode = snapshots[path]
            try:
                _write_bytes_0600(path, data, mode)
            except OSError:
                restore_ok = False
        if not restore_ok:
            raise ConfigSyncError(
                "partial MaiBot config write could not be rolled back; manual recovery required"
            ) from exc
        raise


def sync_maibot_config(instance_dir: Path, *, dry_run: bool = False) -> bool | dict[str, Any]:
    """只执行一次旧模型配置迁移；dry-run 返回就绪报告且不写文件。"""
    base = Path(instance_dir)
    if not base.is_dir():
        raise ConfigSyncError("instance directory does not exist")
    config_dir = base / "config"
    _ensure_within(base, config_dir)
    bot_path = config_dir / BOT_CONFIG_FILENAME
    model_path = config_dir / MODEL_CONFIG_FILENAME
    marker_path = config_dir / MARKER_FILENAME

    marker = _read_marker(marker_path)
    if marker and marker["version"] == MARKER_VERSION:
        if dry_run:
            return config_sync_preflight(base)
        return False
    if marker and marker["version"] == 1:
        report = config_sync_preflight(base)
        if not report["ready"]:
            raise ConfigSyncError(f"native model configuration is invalid: {', '.join(report['reasons'])}")
        if dry_run:
            return report
        _write_text_0600(marker_path, _marker_text())
        return True

    _ensure_plain_file(bot_path)
    _ensure_plain_file(model_path)

    bot_text = bot_path.read_text(encoding="utf-8")
    model_text = model_path.read_text(encoding="utf-8")
    bot_plain = _parse_toml(bot_text, BOT_CONFIG_FILENAME)
    model_plain = _parse_toml(model_text, MODEL_CONFIG_FILENAME)
    _check_inner_version(bot_plain, BOT_CONFIG_VERSION, BOT_CONFIG_FILENAME)
    _check_inner_version(model_plain, MODEL_CONFIG_VERSION, MODEL_CONFIG_FILENAME)
    _check_structure(bot_plain, model_plain)

    legacy_aliases = _verify_v2_aliases(model_plain, marker) if marker else set()
    if not marker:
        _reject_unmarked_proxy_aliases(model_plain)
    plan = _build_plan(model_plain)
    rendered_bot = bot_text if marker else _render_bot(bot_text, plan)
    rendered_model = _render_model(model_text, model_plain, plan, legacy_aliases=legacy_aliases)
    rendered_bot_plain = _parse_toml(rendered_bot, BOT_CONFIG_FILENAME)
    rendered_model_plain = _parse_toml(rendered_model, MODEL_CONFIG_FILENAME)
    _validate_rendered(rendered_bot_plain, rendered_model_plain)

    if dry_run:
        return {"ready": True, "reasons": [], "warnings": list(plan["warnings"])}

    marker_text = _marker_text(plan["warnings"])
    _commit(
        bot_path,
        model_path,
        marker_path,
        rendered_bot if rendered_bot != bot_text else None,
        rendered_model if rendered_model != model_text else None,
        marker_text,
        first_takeover=marker is None,
    )
    return True


def config_sync_preflight(instance_dir: Path | None = None) -> dict[str, Any]:
    """只校验 MaiBot 当前 TOML，不加载或探测 Pallas 模型配置。"""
    reasons: list[str] = []
    warnings: list[str] = []
    if instance_dir is None:
        return {"ready": False, "reasons": ["native_config_unavailable"], "warnings": warnings}
    base = Path(instance_dir)
    try:
        config_dir = base / "config"
        _ensure_within(base, config_dir)
        bot_path = config_dir / BOT_CONFIG_FILENAME
        model_path = config_dir / MODEL_CONFIG_FILENAME
        _ensure_plain_file(bot_path)
        _ensure_plain_file(model_path)
        bot_plain = _parse_toml(bot_path.read_text(encoding="utf-8"), BOT_CONFIG_FILENAME)
        model_plain = _parse_toml(model_path.read_text(encoding="utf-8"), MODEL_CONFIG_FILENAME)
        _check_inner_version(bot_plain, BOT_CONFIG_VERSION, BOT_CONFIG_FILENAME)
        _check_inner_version(model_plain, MODEL_CONFIG_VERSION, MODEL_CONFIG_FILENAME)
        _check_structure(bot_plain, model_plain)
        reasons.extend(_native_config_reasons(model_plain, require_core=True))
        marker = _read_marker(config_dir / MARKER_FILENAME)
        if marker and marker["version"] == MARKER_VERSION:
            warnings.extend(marker["warnings"])
    except (OSError, ConfigSyncError, ValueError):
        reasons.append("native_config_invalid")
    reasons = list(dict.fromkeys(reasons))
    warnings = list(dict.fromkeys(warnings))
    return {"ready": not reasons, "reasons": reasons, "warnings": warnings}
