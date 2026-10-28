"""把共享牛牛人设与 Pallas 全局 LLM 配置同步进 MaiBot 实例 TOML。

一次性接管授权由 ``config_sync_enabled()``（``MAIBOT_CONFIG_SYNC_ENABLED``）体现：
caller 只在显式开启、且实例已停机并持有 start/stop 锁时调用
``sync_maibot_config()``。本模块不做进程探测、不加锁、不启动任何进程。

只 merge 受管字段与 ``pallas-`` 前缀的受管 provider/model，其余表、字段与注释原样保留。
无法在目标侧严格保真的来源（多 key 轮换、日预算封顶、原生 anthropic/ollama 协议）
一律抛 ``ConfigSyncError`` 拒绝，不降级取首项。错误信息不含密钥、上游响应或 TOML 原文。
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any

import tomlkit

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.knowledge.embedding_provider import (
    resolve_embedding_http_endpoint,
    resolve_embedding_provider_name,
    resolve_remote_embedding_model,
)
from pallas.product.llm.provider_client.auth import endpoint_api_keys
from pallas.product.llm.provider_client.mapping import apply_model_effort_to_payload
from pallas.product.llm.provider_client.urls import openai_api_root, resolve_request_method
from pallas.product.llm.providers_store import (
    ResolvedLlmEndpoint,
    find_provider,
    provider_model_reasoning_effort_none_on_disable,
    provider_request_method,
    resolve_endpoint_candidates_for_task,
    resolve_provider_api_keys,
)
from pallas.product.persona.compile_persona_prompt import load_base_system_prompt
from pallas.product.persona.self_identity import extract_generic_self_aliases

CONFIG_SYNC_ENABLED_KEY = "MAIBOT_CONFIG_SYNC_ENABLED"
BOT_CONFIG_FILENAME = "bot_config.toml"
MODEL_CONFIG_FILENAME = "model_config.toml"
MARKER_FILENAME = ".pallas-managed.json"
BOT_CONFIG_VERSION = "8.15.47"
MODEL_CONFIG_VERSION = "1.17.24"
MANAGED_PREFIX = "pallas-"
MARKER_VERSION = 1
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
_EMBEDDING_PROVIDER_TAG = "embed"


class ConfigSyncError(RuntimeError):
    """MaiBot 实例配置无法在目标侧安全同步。"""


def config_sync_enabled() -> bool:
    """``MAIBOT_CONFIG_SYNC_ENABLED``：缺失或空为关闭；非法值明确报错且不回显源值。"""
    raw = repo_env_raw_value(CONFIG_SYNC_ENABLED_KEY)
    if raw is None:
        return False
    text = str(raw).strip().lower()
    if not text:
        return False
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ConfigSyncError(f"{CONFIG_SYNC_ENABLED_KEY} must be a boolean")


def _load_persona_text() -> str:
    return load_base_system_prompt()


def _load_identity_aliases() -> list[str]:
    return list(extract_generic_self_aliases())


def _load_task_chain(task: str) -> list[Any]:
    candidates = list(resolve_endpoint_candidates_for_task(task))
    if candidates:
        return candidates
    return _legacy_task_chain(task)


def _legacy_task_chain(task: str) -> list[Any]:
    """名册无候选时沿实际运行时回退：``LLM_BASE_URL``/``LLM_MODEL`` 单端点。"""
    cfg = get_llm_config()
    base_url = str(getattr(cfg, "llm_base_url", "") or "").strip()
    model = str(getattr(cfg, "llm_model", "") or "").strip()
    if not base_url or not model:
        return []
    api_key = str(getattr(cfg, "llm_api_key", "") or "").strip()
    return [
        ResolvedLlmEndpoint(
            provider_id="",
            base_url=base_url,
            api_key=api_key,
            model=model,
            kind="legacy",
            api_keys=(api_key,) if api_key else (),
        )
    ]


def _load_provider_row(provider_id: str) -> dict[str, Any] | None:
    return find_provider(provider_id)


def _load_chat_budget_limits() -> tuple[int, int]:
    cfg = get_llm_config()
    calls = int(getattr(cfg, "llm_chat_daily_calls_limit", 0) or 0)
    tokens = int(getattr(cfg, "llm_chat_daily_tokens_limit", 0) or 0)
    return calls, tokens


def _load_embedding_source() -> tuple[str, str, str, str] | None:
    """真实 Pallas embedding 线路；stub/local 或未配置端点返回 None。"""
    cfg = get_llm_config()
    if resolve_embedding_provider_name(cfg) != "openai":
        return None
    base_url, api_key, source_id = resolve_embedding_http_endpoint(cfg)
    if not str(base_url or "").strip():
        return None
    model = str(resolve_remote_embedding_model(cfg) or "").strip()
    if not model:
        return None
    return str(base_url).strip(), str(api_key or "").strip(), str(source_id or "").strip(), model


def _assert_budget_and_keys(row: dict[str, Any], provider_id: str) -> None:
    if int(row.get("daily_tokens_cap") or 0) > 0 or float(row.get("daily_cost_cap") or 0.0) > 0:
        raise ConfigSyncError(f"provider {provider_id} has a daily budget cap MaiBot cannot enforce")
    if len(resolve_provider_api_keys(row)) > 1:
        raise ConfigSyncError(f"provider {provider_id} uses multiple api keys MaiBot cannot rotate")


def _global_llm_api_key() -> str:
    cfg = get_llm_config()
    return str(getattr(cfg, "llm_api_key", "") or "").strip()


def _endpoint_api_key(endpoint: Any, provider_tag: str) -> str:
    """Mirror the runtime: provider keys first, else the global ``llm_api_key``."""
    keys = endpoint_api_keys(endpoint, fallback=_global_llm_api_key())
    if len(keys) > 1:
        raise ConfigSyncError(f"provider {provider_tag} uses multiple api keys MaiBot cannot rotate")
    return (keys[0] if keys else "").strip()


def _provider_entry(provider_id: str, base_url: str, api_key: str, client_type: str) -> dict[str, Any]:
    return {
        "name": MANAGED_PREFIX + provider_id,
        "base_url": openai_api_root(base_url),
        "api_key": api_key,
        "client_type": client_type,
        "auth_type": "bearer" if api_key else "none",
    }


def _model_entry(provider_name: str, name: str, model: str, model_type: str, **fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": name,
        "model_identifier": model,
        "model_type": model_type,
        "api_provider": provider_name,
    }
    entry.update(fields)
    return entry


def _merge_chat_endpoint(
    endpoint: Any,
    providers: dict[str, dict[str, Any]],
    models: dict[str, dict[str, Any]],
) -> str:
    provider_id = str(getattr(endpoint, "provider_id", "") or "").strip()
    model = str(getattr(endpoint, "model", "") or "").strip()
    base_url = str(getattr(endpoint, "base_url", "") or "").strip()
    if not model or not base_url:
        raise ConfigSyncError("active route has an incomplete endpoint")
    if provider_id:
        row = _load_provider_row(provider_id)
        if row is None:
            raise ConfigSyncError(f"active route provider {provider_id} is not available")
        _assert_budget_and_keys(row, provider_id)
        request_method = provider_request_method(row)
        api_key = _endpoint_api_key(endpoint, provider_id)
        none_on_disable = provider_model_reasoning_effort_none_on_disable(row, model)
        effort = str(getattr(endpoint, "model_effort", "") or "")
        provider_tag = provider_id
    else:
        # legacy env 单端点：无名册行、无多 key、无 provider 级预算闸
        request_method = "chat_completions"
        api_key = str(getattr(endpoint, "api_key", "") or "").strip()
        none_on_disable = False
        effort = ""
        provider_tag = "legacy"
    method = resolve_request_method(request_method, base_url)
    client_type = _CLIENT_TYPES.get(method)
    if client_type is None:
        raise ConfigSyncError(f"provider {provider_tag} uses a request method MaiBot cannot call natively")
    provider_name = MANAGED_PREFIX + provider_tag
    provider = _provider_entry(provider_tag, base_url, api_key, client_type)
    existing_provider = providers.get(provider_name)
    if existing_provider is not None and existing_provider != provider:
        raise ConfigSyncError(f"provider {provider_tag} is configured inconsistently across tasks")
    providers[provider_name] = provider
    payload: dict[str, Any] = {"model": model}
    apply_model_effort_to_payload(
        payload,
        {"model_effort": effort},
        model=model,
        request_method=method,
        reasoning_effort_none_on_disable=none_on_disable,
    )
    extra_params = {key: value for key, value in payload.items() if key != "model"}
    capabilities = tuple(getattr(endpoint, "capabilities", ()) or ())
    name = f"{MANAGED_PREFIX}{provider_tag}-{model}"
    entry = _model_entry(
        provider_name,
        name,
        model,
        "llm",
        visual="image" in capabilities,
        force_stream_mode=provider_tag == "cpa",
        extra_params=extra_params,
    )
    existing_model = models.get(name)
    if existing_model is not None and existing_model != entry:
        raise ConfigSyncError(f"model {name} resolves to conflicting parameters")
    models[name] = entry
    return name


def _build_chat_targets() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    chains: dict[str, list[Any]] = {}
    for source_task in dict.fromkeys(LLM_TASK_SOURCES.values()):
        chain = _load_task_chain(source_task)
        if not chain:
            raise ConfigSyncError(f"no usable endpoint is configured for task {source_task}")
        if len(chain) > 1:
            raise ConfigSyncError(f"task {source_task} resolves to a fallback chain MaiBot cannot preserve")
        chains[source_task] = chain
    calls_limit, tokens_limit = _load_chat_budget_limits()
    if calls_limit > 0 or tokens_limit > 0:
        raise ConfigSyncError("llm_chat daily budget cap cannot be enforced in MaiBot")
    providers: dict[str, dict[str, Any]] = {}
    models: dict[str, dict[str, Any]] = {}
    tasks: dict[str, dict[str, Any]] = {}
    for task_key, source_task in LLM_TASK_SOURCES.items():
        names = [_merge_chat_endpoint(endpoint, providers, models) for endpoint in chains[source_task]]
        tasks[task_key] = {
            "model_list": names,
            "selection_strategy": "sequential",
        }
    return providers, models, tasks


def _build_embedding_target() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]] | None:
    source = _load_embedding_source()
    if source is None:
        return None
    base_url, api_key, source_id, model = source
    if source_id:
        row = _load_provider_row(source_id)
        if row is not None:
            _assert_budget_and_keys(row, source_id)
    provider_id = f"{_EMBEDDING_PROVIDER_TAG}-{source_id}" if source_id else _EMBEDDING_PROVIDER_TAG
    provider_name = MANAGED_PREFIX + provider_id
    provider = _provider_entry(provider_id, base_url, api_key, "openai")
    name = f"{MANAGED_PREFIX}{provider_id}-{model}"
    entry = _model_entry(
        provider_name,
        name,
        model,
        "embedding",
        visual=False,
        force_stream_mode=False,
        extra_params={},
    )
    return {provider_name: provider}, {name: entry}


def _merge_managed(target: dict[str, dict[str, Any]], incoming: dict[str, dict[str, Any]], kind: str) -> None:
    for name, entry in incoming.items():
        existing = target.get(name)
        if existing is not None and existing != entry:
            raise ConfigSyncError(f"managed {kind} name collision with different content: {name}")
        target[name] = entry


def _build_plan() -> dict[str, Any]:
    providers, models, tasks = _build_chat_targets()
    managed_task_keys = list(LLM_TASK_SOURCES)
    embedding = _build_embedding_target()
    if embedding is not None:
        embed_providers, embed_models = embedding
        _merge_managed(providers, embed_providers, "provider")
        _merge_managed(models, embed_models, "model")
        tasks["embedding"] = {
            "model_list": list(embed_models),
            "selection_strategy": "sequential",
        }
        managed_task_keys.append("embedding")
    aliases = [alias for alias in _load_identity_aliases() if str(alias).strip()]
    nickname = aliases[0] if aliases else "牛牛"
    return {
        "persona": _load_persona_text(),
        "nickname": nickname,
        "alias_names": aliases,
        "providers": providers,
        "models": models,
        "tasks": tasks,
        "managed_task_keys": managed_task_keys,
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


def _merge_table(table: Any, entry: dict[str, Any]) -> None:
    """Update only the managed keys of an existing table, keeping other keys and comments."""
    for key, value in entry.items():
        table[key] = _toml_value(value)


def _render_bot(bot_text: str, plan: dict[str, Any]) -> str:
    doc = tomlkit.parse(bot_text)
    for section in ("bot", "personality"):
        if not isinstance(doc.get(section), dict):
            doc[section] = tomlkit.table()
    doc["bot"]["nickname"] = plan["nickname"]
    doc["bot"]["alias_names"] = _toml_value(list(plan["alias_names"]))
    doc["personality"]["personality"] = plan["persona"]
    return tomlkit.dumps(doc)


def _unmanaged_referenced(plain: dict[str, Any], managed_task_keys: list[str]) -> set[str]:
    referenced: set[str] = set()
    for key, sub in (plain.get("model_task_config") or {}).items():
        if key in managed_task_keys or not isinstance(sub, dict):
            continue
        referenced.update(str(name) for name in sub.get("model_list") or [])
    return referenced


def _render_model(model_text: str, model_plain: dict[str, Any], plan: dict[str, Any]) -> str:
    doc = tomlkit.parse(model_text)
    desired_models: dict[str, dict[str, Any]] = plan["models"]
    desired_providers: dict[str, dict[str, Any]] = plan["providers"]
    unmanaged = _unmanaged_referenced(model_plain, plan["managed_task_keys"])
    plain_models = {str(row.get("name") or ""): row for row in model_plain.get("models") or []}

    models_aot = doc.get("models")
    if not isinstance(models_aot, list):
        models_aot = tomlkit.aot()
        doc["models"] = models_aot
    existing_models = {str(item.get("name") or ""): item for item in models_aot}
    kept_models = []
    for item in models_aot:
        name = str(item.get("name") or "")
        if name in desired_models:
            continue
        if name.startswith(MANAGED_PREFIX) and name not in unmanaged:
            continue
        kept_models.append(item)
    referenced_providers = {
        str(plain_models[name].get("api_provider") or "")
        for name in (str(item.get("name") or "") for item in kept_models)
        if name in plain_models
    }
    del models_aot[:]
    for item in kept_models:
        models_aot.append(item)
    for name, entry in desired_models.items():
        existing = existing_models.get(name)
        if existing is not None:
            _merge_table(existing, entry)
            models_aot.append(existing)
        else:
            models_aot.append(_to_table(entry))

    providers_aot = doc.get("api_providers")
    if not isinstance(providers_aot, list):
        providers_aot = tomlkit.aot()
        doc["api_providers"] = providers_aot
    existing_providers = {str(item.get("name") or ""): item for item in providers_aot}
    kept_providers = []
    for item in providers_aot:
        name = str(item.get("name") or "")
        if name in desired_providers:
            continue
        if name.startswith(MANAGED_PREFIX) and name not in referenced_providers:
            continue
        kept_providers.append(item)
    del providers_aot[:]
    for item in kept_providers:
        providers_aot.append(item)
    for name, entry in desired_providers.items():
        existing = existing_providers.get(name)
        if existing is not None:
            _merge_table(existing, entry)
            providers_aot.append(existing)
        else:
            providers_aot.append(_to_table(entry))

    mtc = doc.get("model_task_config")
    if not isinstance(mtc, dict):
        mtc = tomlkit.table()
        doc["model_task_config"] = mtc
    for key, config in plan["tasks"].items():
        sub = mtc.get(key)
        if not isinstance(sub, dict):
            sub = tomlkit.table()
            mtc[key] = sub
        for field, value in config.items():
            sub[field] = _toml_value(value)
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


def _validate_task_ranges(key: str, config: dict[str, Any]) -> None:
    max_tokens = config.get("max_tokens")
    if max_tokens is not None and (not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1):
        raise ConfigSyncError(f"model_task_config.{key}.max_tokens is out of range")
    temperature = config.get("temperature")
    if temperature is not None:
        valid = isinstance(temperature, (int, float)) and not isinstance(temperature, bool) and 0 <= temperature <= 2
        if not valid:
            raise ConfigSyncError(f"model_task_config.{key}.temperature is out of range")
    strategy = config.get("selection_strategy")
    if strategy is not None and str(strategy) not in {"balance", "random", "sequential"}:
        raise ConfigSyncError(f"model_task_config.{key}.selection_strategy is invalid")


def _validate_rendered(bot_plain: dict[str, Any], model_plain: dict[str, Any]) -> None:
    _check_inner_version(bot_plain, BOT_CONFIG_VERSION, BOT_CONFIG_FILENAME)
    _check_inner_version(model_plain, MODEL_CONFIG_VERSION, MODEL_CONFIG_FILENAME)
    _check_structure(bot_plain, model_plain)
    personality = bot_plain.get("personality") or {}
    if not str(personality.get("personality") or "").strip():
        raise ConfigSyncError("rendered personality is empty")
    providers = _rows(model_plain, "api_providers", MODEL_CONFIG_FILENAME)
    provider_names = [str(row.get("name") or "") for row in providers]
    if len(provider_names) != len(set(provider_names)):
        raise ConfigSyncError("rendered api_providers contain duplicate names")
    models = _rows(model_plain, "models", MODEL_CONFIG_FILENAME)
    model_names = [str(row.get("name") or "") for row in models]
    if len(model_names) != len(set(model_names)):
        raise ConfigSyncError("rendered models contain duplicate names")
    known = set(provider_names)
    by_name = {str(row.get("name") or ""): row for row in models}
    for row in models:
        name = str(row.get("name") or "")
        model_type = str(row.get("model_type") or "")
        if not name or not str(row.get("model_identifier") or ""):
            raise ConfigSyncError("rendered model is missing a name or identifier")
        if model_type not in {"llm", "embedding", "image_embedding"}:
            raise ConfigSyncError(f"rendered model {name} has an invalid model_type")
        if str(row.get("api_provider") or "") not in known:
            raise ConfigSyncError(f"rendered model {name} references an unknown provider")
    for provider in providers:
        name = str(provider.get("name") or "")
        if not name:
            raise ConfigSyncError("rendered provider is missing a name")
        if not str(provider.get("base_url") or "") and str(provider.get("client_type") or "") != "gemini":
            raise ConfigSyncError(f"rendered provider {name} is missing a base_url")
        if str(provider.get("auth_type") or "") != "none" and not str(provider.get("api_key") or ""):
            raise ConfigSyncError(f"rendered provider {name} is missing an api_key")
    mtc = _table(model_plain, "model_task_config", MODEL_CONFIG_FILENAME)
    for key, config in mtc.items():
        if not isinstance(config, dict) or "model_list" not in config:
            continue
        model_list = config.get("model_list")
        if not isinstance(model_list, list):
            raise ConfigSyncError(f"model_task_config.{key}.model_list must be a list")
        for name in model_list:
            row = by_name.get(str(name))
            if row is None:
                raise ConfigSyncError(f"task {key} references an undefined model")
            if key in {"embedding", "image_embedding"}:
                # 上游说明：embedding / image_embedding 均可引用文本或图片嵌入类型
                if str(row.get("model_type") or "") not in {"embedding", "image_embedding"}:
                    raise ConfigSyncError(f"task {key} must reference an embedding model")
            elif str(row.get("model_type") or "") != "llm":
                raise ConfigSyncError(f"task {key} must reference an llm model")
        _validate_task_ranges(key, config)


def _projection(
    bot_plain: dict[str, Any],
    model_plain: dict[str, Any],
    *,
    provider_names: list[str],
    model_names: list[str],
    task_keys: list[str],
) -> dict[str, Any]:
    bot = bot_plain.get("bot") or {}
    personality = bot_plain.get("personality") or {}
    providers = {str(row.get("name") or ""): row for row in model_plain.get("api_providers") or []}
    models = {str(row.get("name") or ""): row for row in model_plain.get("models") or []}
    mtc = model_plain.get("model_task_config") or {}

    def provider_view(name: str) -> dict[str, Any] | None:
        row = providers.get(name)
        if not isinstance(row, dict):
            return None
        return {
            "base_url": str(row.get("base_url") or ""),
            "api_key": str(row.get("api_key") or ""),
            "client_type": str(row.get("client_type") or ""),
            "auth_type": str(row.get("auth_type") or ""),
        }

    def model_view(name: str) -> dict[str, Any] | None:
        row = models.get(name)
        if not isinstance(row, dict):
            return None
        return {
            "model_identifier": str(row.get("model_identifier") or ""),
            "model_type": str(row.get("model_type") or ""),
            "api_provider": str(row.get("api_provider") or ""),
            "visual": bool(row.get("visual")),
            "force_stream_mode": bool(row.get("force_stream_mode")),
            "extra_params": dict(row.get("extra_params") or {}),
        }

    def task_view(key: str) -> dict[str, Any] | None:
        sub = mtc.get(key)
        if not isinstance(sub, dict):
            return None
        return {
            "model_list": [str(name) for name in sub.get("model_list") or []],
            "selection_strategy": str(sub.get("selection_strategy") or ""),
        }

    return {
        "nickname": str(bot.get("nickname") or ""),
        "alias_names": [str(name) for name in bot.get("alias_names") or []],
        "personality": str(personality.get("personality") or ""),
        "api_providers": {name: provider_view(name) for name in provider_names},
        "models": {name: model_view(name) for name in model_names},
        "model_task_config": {key: task_view(key) for key in task_keys},
    }


def _digest(projection: dict[str, Any]) -> str:
    payload = json.dumps(projection, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
    if not isinstance(data, dict) or data.get("version") != MARKER_VERSION:
        raise ConfigSyncError("managed marker has an unsupported schema")
    return data


def _marker_text(
    projection: dict[str, Any], *, provider_names: list[str], model_names: list[str], task_keys: list[str]
) -> str:
    payload = {
        "version": MARKER_VERSION,
        "bot_config_version": BOT_CONFIG_VERSION,
        "model_config_version": MODEL_CONFIG_VERSION,
        "digest": _digest(projection),
        "provider_names": provider_names,
        "model_names": model_names,
        "task_keys": task_keys,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
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
    bot_text: str,
    model_text: str,
    marker_text: str,
    *,
    first_takeover: bool,
) -> None:
    snapshots = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in (bot_path, model_path)}
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
        for path, text in ((bot_path, bot_text), (model_path, model_text), (marker_path, marker_text)):
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


def sync_maibot_config(instance_dir: Path, *, dry_run: bool = False) -> bool:
    """把共享人设与全局 LLM 配置 merge 进实例 TOML，返回是否有改动。

    caller 必须保证实例已停机并持有 start/stop 锁。``dry_run=True`` 只校验渲染，
    不写文件 / 备份 / marker / 目录。
    """
    base = Path(instance_dir)
    if not base.is_dir():
        raise ConfigSyncError("instance directory does not exist")
    config_dir = base / "config"
    _ensure_within(base, config_dir)
    bot_path = config_dir / BOT_CONFIG_FILENAME
    model_path = config_dir / MODEL_CONFIG_FILENAME
    marker_path = config_dir / MARKER_FILENAME
    _ensure_plain_file(bot_path)
    _ensure_plain_file(model_path)

    bot_text = bot_path.read_text(encoding="utf-8")
    model_text = model_path.read_text(encoding="utf-8")
    bot_plain = _parse_toml(bot_text, BOT_CONFIG_FILENAME)
    model_plain = _parse_toml(model_text, MODEL_CONFIG_FILENAME)
    _check_inner_version(bot_plain, BOT_CONFIG_VERSION, BOT_CONFIG_FILENAME)
    _check_inner_version(model_plain, MODEL_CONFIG_VERSION, MODEL_CONFIG_FILENAME)
    _check_structure(bot_plain, model_plain)

    plan = _build_plan()
    rendered_bot = _render_bot(bot_text, plan)
    rendered_model = _render_model(model_text, model_plain, plan)
    rendered_bot_plain = _parse_toml(rendered_bot, BOT_CONFIG_FILENAME)
    rendered_model_plain = _parse_toml(rendered_model, MODEL_CONFIG_FILENAME)
    _validate_rendered(rendered_bot_plain, rendered_model_plain)

    provider_names = list(plan["providers"])
    model_names = list(plan["models"])
    task_keys = list(plan["managed_task_keys"])
    desired = _projection(
        rendered_bot_plain,
        rendered_model_plain,
        provider_names=provider_names,
        model_names=model_names,
        task_keys=task_keys,
    )
    desired_digest = _digest(desired)

    marker = _read_marker(marker_path)
    if marker is not None:
        current = _projection(
            bot_plain,
            model_plain,
            provider_names=list(marker.get("provider_names") or []),
            model_names=list(marker.get("model_names") or []),
            task_keys=list(marker.get("task_keys") or []),
        )
        if _digest(current) != str(marker.get("digest") or ""):
            raise ConfigSyncError("managed MaiBot config was edited outside Pallas; refusing to overwrite")
        if desired_digest == str(marker.get("digest") or ""):
            return False

    if dry_run:
        return True

    marker_text = _marker_text(desired, provider_names=provider_names, model_names=model_names, task_keys=task_keys)
    _commit(
        bot_path,
        model_path,
        marker_path,
        rendered_bot,
        rendered_model,
        marker_text,
        first_takeover=marker is None,
    )
    return True
