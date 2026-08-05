"""Bot 侧 LLM Provider 事实源（取代 AI providers.toml 作为聊天配置）。"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003
from typing import Any

from nonebot import logger

from pallas.core.foundation.paths import DATA_ROOT, PROJECT_ROOT
from pallas.product.llm.provider_client import mask_api_key_hint

_LOCK = threading.RLock()
_DOC_CACHE: dict[str, Any] | None = None
# hub 写入后 worker 靠磁盘 revision 失效缓存（同 repo_settings）
_DOC_CACHE_REV: tuple[int, int] | None = None

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:11434"
PROVIDERS_FILENAME = "llm_providers.json"


def providers_store_path() -> Path:
    return DATA_ROOT / "pallas_config" / PROVIDERS_FILENAME


def providers_store_disk_revision() -> tuple[int, int] | None:
    """返回 (mtime_ns, size)；文件不存在则为 None。"""
    path = providers_store_path()
    if not path.is_file():
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    return (int(st.st_mtime_ns), int(st.st_size))


def clear_providers_store_cache() -> None:
    global _DOC_CACHE, _DOC_CACHE_REV
    with _LOCK:
        _DOC_CACHE = None
        _DOC_CACHE_REV = None


def _empty_document() -> dict[str, Any]:
    return {
        "providers": [],
        "routing": {
            "chain_fallback": [],
            "tasks": {},
            "tier_backups": {},
            "tier_backup_models": {},
            "task_backups": {},
            "task_backup_models": {},
            "cost_currency": "",
        },
    }


def _looks_like_inline_api_key(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if text.startswith(("sk-", "Bearer ")):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", text):
        return False
    return len(text) >= 24


def _normalize_api_keys(raw: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    raw_keys = raw.get("api_keys")
    if isinstance(raw_keys, list):
        for item in raw_keys:
            key = str(item or "").strip()
            if key and key not in seen:
                keys.append(key)
                seen.add(key)
    single = str(raw.get("api_key") or "").strip()
    if single and single not in seen:
        keys.insert(0, single)
    return keys


def _provider_api_key_set(raw: dict[str, Any]) -> bool:
    if _normalize_api_keys(raw):
        return True
    env_name = str(raw.get("api_key_env") or "").strip()
    if env_name and not _looks_like_inline_api_key(env_name):
        return bool(str(os.environ.get(env_name) or "").strip())
    return False


def resolve_provider_api_key(raw: dict[str, Any]) -> str:
    keys = resolve_provider_api_keys(raw)
    return keys[0] if keys else ""


def resolve_provider_api_keys(raw: dict[str, Any]) -> list[str]:
    """有序密钥列表：第 0 项为主用，其后为同 Provider 备用。"""
    keys = _normalize_api_keys(raw)
    if keys:
        return list(keys)
    env_name = str(raw.get("api_key_env") or "").strip()
    if env_name and not _looks_like_inline_api_key(env_name):
        value = str(os.environ.get(env_name) or "").strip()
        return [value] if value else []
    if env_name and _looks_like_inline_api_key(env_name):
        return [env_name]
    return []


PROVIDER_CAPABILITIES = ("text", "image", "audio", "video")
PROVIDER_MODEL_EFFORTS = (
    "enable",
    "disable",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
PROVIDER_REQUEST_METHODS = ("chat_completions", "responses", "anthropic_messages")
DEFAULT_REQUEST_METHOD = "chat_completions"


def _normalize_capabilities(raw: dict[str, Any]) -> list[str]:
    allowed = set(PROVIDER_CAPABILITIES)
    out: list[str] = []
    seen: set[str] = set()
    value = raw.get("capabilities")
    if not isinstance(value, list):
        return out
    for item in value:
        cap = str(item or "").strip().lower()
        if cap in allowed and cap not in seen:
            out.append(cap)
            seen.add(cap)
    return out


def _normalize_model_effort(raw: dict[str, Any]) -> str:
    value = str(raw.get("model_effort") or "").strip().lower()
    if value in PROVIDER_MODEL_EFFORTS:
        return value
    return ""


def _normalize_request_method(raw: dict[str, Any]) -> str:
    value = str(raw.get("request_method") or "").strip().lower()
    if value in PROVIDER_REQUEST_METHODS:
        return value
    return DEFAULT_REQUEST_METHOD


def provider_capabilities(row: dict[str, Any] | None) -> list[str]:
    if not isinstance(row, dict):
        return []
    return _normalize_capabilities(row)


def provider_supports_capability(row: dict[str, Any] | None, capability: str) -> bool:
    """能力列表为空视为遗留配置：不限制；显式声明后才按白名单判断。"""
    cap = str(capability or "").strip().lower()
    if not cap:
        return False
    caps = provider_capabilities(row)
    if not caps:
        return True
    return cap in caps


def provider_allows_native_vision(row: dict[str, Any] | None) -> bool:
    """仅当显式声明 image 时走原生多模态；未配置能力则不默认看图。"""
    return "image" in provider_capabilities(row)


def provider_needs_vision_text_fallback(row: dict[str, Any] | None) -> bool:
    """含图且未声明 image 时，转成文字描述/占位。"""
    return not provider_allows_native_vision(row)


def provider_model_effort(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return _normalize_model_effort(row)


def provider_request_method(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return DEFAULT_REQUEST_METHOD
    kind = str(row.get("kind") or "").strip().lower()
    if kind == "local":
        return DEFAULT_REQUEST_METHOD
    return _normalize_request_method(row)


def resolve_provider_base_url(raw: dict[str, Any]) -> str:
    url = str(raw.get("base_url") or "").strip()
    if url:
        return url
    kind = str(raw.get("kind") or "").strip().lower()
    if kind == "local" or str(raw.get("id") or "").strip().lower() == "local":
        return DEFAULT_LOCAL_BASE_URL
    return ""


def _normalize_provider_row(raw: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any] | None:
    pid = str(raw.get("id") or "").strip()
    if not pid:
        return None
    kind = str(raw.get("kind") or "remote").strip().lower() or "remote"
    api_keys = _normalize_api_keys(raw)
    api_key_env = str(raw.get("api_key_env") or "").strip()
    if not api_keys and api_key_env and _looks_like_inline_api_key(api_key_env):
        api_keys = [api_key_env]
        api_key_env = ""
    # 入参无可用密钥时默认保留已有。显式清空须 clear_api_keys=true
    # （WebUI PUT 经 Pydantic 常注入 api_keys=[]，否则会误擦密钥）。
    clear_api_keys = bool(raw.get("clear_api_keys"))
    if not api_keys and not api_key_env and existing and not clear_api_keys:
        prev_keys = _normalize_api_keys(existing)
        prev_env = str(existing.get("api_key_env") or "").strip()
        if prev_keys:
            api_keys = prev_keys
        elif prev_env:
            api_key_env = prev_env
    api_key = api_keys[0] if api_keys else ""
    task_models_raw = raw.get("task_models")
    if not isinstance(task_models_raw, dict):
        task_models_raw = raw.get("models")
    task_models: dict[str, str] = {}
    if isinstance(task_models_raw, dict):
        for key, value in task_models_raw.items():
            task = str(key or "").strip()
            model = str(value or "").strip()
            if task and model:
                task_models[task] = model
    capabilities = _normalize_capabilities(raw)
    if "capabilities" not in raw and existing:
        capabilities = _normalize_capabilities(existing)
    model_effort = _normalize_model_effort(raw)
    if "model_effort" not in raw and existing:
        model_effort = _normalize_model_effort(existing)
    request_method = _normalize_request_method(raw)
    if "request_method" not in raw and existing:
        request_method = _normalize_request_method(existing)
    if kind == "local":
        request_method = DEFAULT_REQUEST_METHOD
    from pallas.product.llm.token_cost import normalize_model_pricing

    if "model_pricing" in raw:
        model_pricing = normalize_model_pricing(raw.get("model_pricing"))
    elif existing and isinstance(existing.get("model_pricing"), dict):
        model_pricing = normalize_model_pricing(existing.get("model_pricing"))
    else:
        model_pricing = {}
    return {
        "id": pid,
        "kind": kind,
        "base_url": str(raw.get("base_url") or "").strip(),
        "api_key": api_key,
        "api_keys": api_keys,
        "api_key_env": api_key_env,
        "default_model": str(raw.get("default_model") or "").strip(),
        "enabled": bool(raw.get("enabled", True)),
        "task_models": task_models,
        "capabilities": capabilities,
        "model_effort": model_effort,
        "request_method": request_method,
        "model_pricing": model_pricing,
    }


def _normalize_tier_str_map(raw: object) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for key in ("high", "low"):
        value = str(raw.get(key) or "").strip()
        if value:
            out[key] = value
    return out


def _normalize_task_str_map(raw: object) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        task = str(key or "").strip()
        item = str(value or "").strip()
        if task and item:
            out[task] = item
    return out


def _merge_routing_tier_maps(
    routing_out: dict[str, Any],
    routing_raw: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
    field: str,
) -> None:
    """显式字段优先；请求未带时保留已落盘值，避免其它页保存冲掉。"""
    if field in routing_raw:
        routing_out[field] = _normalize_tier_str_map(routing_raw.get(field))
        return
    if not existing:
        return
    prev_routing = existing.get("routing") if isinstance(existing.get("routing"), dict) else {}
    if isinstance(prev_routing, dict) and field in prev_routing:
        routing_out[field] = _normalize_tier_str_map(prev_routing.get(field))


def _merge_routing_task_maps(
    routing_out: dict[str, Any],
    routing_raw: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
    field: str,
) -> None:
    if field in routing_raw:
        routing_out[field] = _normalize_task_str_map(routing_raw.get(field))
        return
    if not existing:
        return
    prev_routing = existing.get("routing") if isinstance(existing.get("routing"), dict) else {}
    if isinstance(prev_routing, dict) and field in prev_routing:
        routing_out[field] = _normalize_task_str_map(prev_routing.get(field))


def _merge_route_source(
    routing_out: dict[str, Any],
    routing_raw: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
) -> None:
    if "route_source" in routing_raw:
        raw = str(routing_raw.get("route_source") or "").strip().lower()
        if raw in ("tiers", "tasks"):
            routing_out["route_source"] = raw
        return
    if not existing:
        return
    prev_routing = existing.get("routing") if isinstance(existing.get("routing"), dict) else {}
    if isinstance(prev_routing, dict):
        raw = str(prev_routing.get("route_source") or "").strip().lower()
        if raw in ("tiers", "tasks"):
            routing_out["route_source"] = raw


def _normalize_document(raw: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing_by_id: dict[str, dict[str, Any]] = {}
    if existing:
        for row in existing.get("providers") or []:
            if isinstance(row, dict) and str(row.get("id") or "").strip():
                existing_by_id[str(row["id"]).strip()] = row
    providers: list[dict[str, Any]] = []
    for item in raw.get("providers") or []:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        normalized = _normalize_provider_row(item, existing_by_id.get(pid))
        if normalized:
            providers.append(normalized)
    routing_raw = raw.get("routing") if isinstance(raw.get("routing"), dict) else {}
    chain = routing_raw.get("chain_fallback")
    if not isinstance(chain, list):
        chain = []
    tasks_raw = routing_raw.get("tasks")
    tasks: dict[str, str] = {}
    if isinstance(tasks_raw, dict):
        for key, value in tasks_raw.items():
            task = str(key or "").strip()
            provider_id = str(value or "").strip()
            if task and provider_id:
                tasks[task] = provider_id
    # tier_*：高低档兜底；task_*：全任务覆盖（并存时运行时以 task_* 为准）
    routing_out: dict[str, Any] = {
        "chain_fallback": [str(item).strip() for item in chain if str(item).strip()],
        "tasks": tasks,
    }
    _merge_routing_tier_maps(routing_out, routing_raw, existing=existing, field="tier_backups")
    _merge_routing_tier_maps(routing_out, routing_raw, existing=existing, field="tier_backup_models")
    _merge_routing_task_maps(routing_out, routing_raw, existing=existing, field="task_backups")
    _merge_routing_task_maps(routing_out, routing_raw, existing=existing, field="task_backup_models")
    _merge_route_source(routing_out, routing_raw, existing=existing)
    from pallas.product.llm.token_cost import normalize_cost_currency

    if "cost_currency" in routing_raw:
        routing_out["cost_currency"] = normalize_cost_currency(routing_raw.get("cost_currency"))
    elif existing:
        prev_routing = existing.get("routing") if isinstance(existing.get("routing"), dict) else {}
        if isinstance(prev_routing, dict) and "cost_currency" in prev_routing:
            routing_out["cost_currency"] = normalize_cost_currency(prev_routing.get("cost_currency"))
        else:
            routing_out["cost_currency"] = ""
    else:
        routing_out["cost_currency"] = ""
    return {
        "providers": providers,
        "routing": routing_out,
    }


def _read_ai_providers_toml() -> dict[str, Any] | None:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    from pallas.console.cli.ai_ops import resolve_ai_repo_root

    roots: list[Path] = []
    ai_root = resolve_ai_repo_root()
    if ai_root is not None:
        roots.append(ai_root)
    sibling = (PROJECT_ROOT.parent / "Pallas-Bot-AI").resolve()
    if sibling not in roots:
        roots.append(sibling)
    for root in roots:
        path = root / "config" / "providers.toml"
        if not path.is_file():
            continue
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except Exception:
            logger.exception("import ai providers.toml failed: path={}", path)
            continue
        if not isinstance(data, dict):
            continue
        logger.info("imported llm providers from {}", path)
        return data
    return None


def _ensure_seeded_document() -> dict[str, Any]:
    path = providers_store_path()
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("read llm providers store failed: path={}", path)
            return _empty_document()
        if isinstance(payload, dict):
            return _normalize_document(payload)
        return _empty_document()
    imported = _read_ai_providers_toml()
    if imported is None:
        return _empty_document()
    doc = _normalize_document(imported)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.info("seeded bot llm providers store: path={}", path)
    except Exception:
        logger.exception("seed llm providers store failed: path={}", path)
    return doc


def load_providers_document(*, refresh: bool = False) -> dict[str, Any]:
    global _DOC_CACHE, _DOC_CACHE_REV
    with _LOCK:
        rev = providers_store_disk_revision()
        if _DOC_CACHE is not None and not refresh and _DOC_CACHE_REV == rev:
            return json.loads(json.dumps(_DOC_CACHE))
        doc = _ensure_seeded_document()
        _DOC_CACHE = json.loads(json.dumps(doc))
        _DOC_CACHE_REV = providers_store_disk_revision()
        return json.loads(json.dumps(_DOC_CACHE))


def save_providers_document(document: dict[str, Any]) -> dict[str, Any]:
    global _DOC_CACHE, _DOC_CACHE_REV
    existing = load_providers_document(refresh=True)
    normalized = _normalize_document(document if isinstance(document, dict) else {}, existing=existing)
    path = providers_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with _LOCK:
        _DOC_CACHE = json.loads(json.dumps(normalized))
        _DOC_CACHE_REV = providers_store_disk_revision()
    logger.info("llm providers saved: file={}", path)
    return export_providers_for_api(doc=normalized)


def upsert_provider_row(provider: dict[str, Any]) -> dict[str, Any]:
    """只更新单个提供方；其余行原样保留（避免整表 PUT 误擦其他密钥）。"""
    global _DOC_CACHE, _DOC_CACHE_REV
    if not isinstance(provider, dict):
        raise ValueError("provider must be an object")
    existing = load_providers_document(refresh=True)
    existing_rows = [row for row in (existing.get("providers") or []) if isinstance(row, dict)]
    existing_by_id = {
        str(row.get("id") or "").strip(): row for row in existing_rows if str(row.get("id") or "").strip()
    }
    pid = str(provider.get("id") or "").strip()
    if not pid:
        raise ValueError("provider id is required")
    normalized = _normalize_provider_row(provider, existing_by_id.get(pid))
    if normalized is None:
        raise ValueError("invalid provider")
    next_rows: list[dict[str, Any]] = []
    replaced = False
    for row in existing_rows:
        rid = str(row.get("id") or "").strip()
        if rid == pid:
            next_rows.append(normalized)
            replaced = True
        else:
            # 其他提供方整行拷贝，不重跑密钥归一化，杜绝连带清空
            next_rows.append(json.loads(json.dumps(row)))
    if not replaced:
        next_rows.append(normalized)
    routing = existing.get("routing") if isinstance(existing.get("routing"), dict) else {}
    doc = {
        "providers": next_rows,
        "routing": {
            "chain_fallback": list(routing.get("chain_fallback") or []),
            "tasks": dict(routing.get("tasks") or {}),
            "tier_backups": dict(routing.get("tier_backups") or {}),
            "tier_backup_models": dict(routing.get("tier_backup_models") or {}),
            "task_backups": dict(routing.get("task_backups") or {}),
            "task_backup_models": dict(routing.get("task_backup_models") or {}),
            "route_source": str(routing.get("route_source") or ""),
            "cost_currency": str(routing.get("cost_currency") or ""),
        },
    }
    path = providers_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with _LOCK:
        _DOC_CACHE = json.loads(json.dumps(doc))
        _DOC_CACHE_REV = providers_store_disk_revision()
    logger.info("llm provider upserted: id={} file={}", pid, path)
    return export_providers_for_api(doc=doc)


def export_providers_for_api(*, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = doc if isinstance(doc, dict) else load_providers_document()
    providers: list[dict[str, Any]] = []
    for raw in payload.get("providers") or []:
        if not isinstance(raw, dict):
            continue
        api_key_env = str(raw.get("api_key_env") or "").strip()
        if _looks_like_inline_api_key(api_key_env):
            api_key_env = ""
        api_keys = _normalize_api_keys(raw)
        providers.append({
            "id": str(raw.get("id") or "").strip(),
            "kind": str(raw.get("kind") or "remote").strip().lower(),
            "base_url": str(raw.get("base_url") or "").strip(),
            "api_key_env": api_key_env,
            "api_key_set": _provider_api_key_set(raw),
            # 读取配置不回传历史密钥；空 key 保存时会保留落盘值。
            "api_key": "",
            "api_keys": [],
            "api_key_hints": [mask_api_key_hint(key) for key in api_keys],
            "api_keys_count": len(api_keys),
            "default_model": str(raw.get("default_model") or "").strip(),
            "enabled": bool(raw.get("enabled", True)),
            "task_models": dict(raw.get("task_models") or {}),
            "capabilities": _normalize_capabilities(raw),
            "model_effort": _normalize_model_effort(raw),
            "request_method": provider_request_method(raw),
            "model_pricing": dict(raw.get("model_pricing") or {}),
        })
    path = providers_store_path()
    routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
    return {
        "providers": providers,
        "routing": routing
        or {
            "chain_fallback": [],
            "tasks": {},
            "tier_backups": {},
            "tier_backup_models": {},
            "task_backups": {},
            "task_backup_models": {},
            "cost_currency": "",
        },
        "providers_file": str(path),
        "file_exists": path.is_file(),
    }


def find_provider(
    provider_id: str,
    *,
    doc: dict[str, Any] | None = None,
    include_disabled: bool = False,
) -> dict[str, Any] | None:
    """按 id 查找提供方。默认跳过已禁用（路由用）；连通探测可 include_disabled=True。"""
    pid = str(provider_id or "").strip()
    if not pid:
        return None
    payload = doc if isinstance(doc, dict) else load_providers_document()
    for row in payload.get("providers") or []:
        if isinstance(row, dict) and str(row.get("id") or "").strip() == pid:
            if not include_disabled and row.get("enabled", True) is False:
                return None
            return row
    return None


def provider_task_model(row: dict[str, Any], task: str) -> str:
    task_name = str(task or "").strip()
    models = row.get("task_models") if isinstance(row.get("task_models"), dict) else {}
    if task_name and isinstance(models, dict):
        model = str(models.get(task_name) or "").strip()
        if model:
            return model
    return str(row.get("default_model") or "").strip()


@dataclass(frozen=True, slots=True)
class ResolvedLlmEndpoint:
    provider_id: str
    base_url: str
    api_key: str
    model: str
    kind: str = "remote"
    capabilities: tuple[str, ...] = ()
    model_effort: str = ""
    request_method: str = DEFAULT_REQUEST_METHOD
    api_keys: tuple[str, ...] = ()


def resolve_endpoint_candidates_for_task(task: str = "llm_chat") -> list[ResolvedLlmEndpoint]:
    doc = load_providers_document()
    task_name = str(task or "llm_chat").strip().lower() or "llm_chat"
    routing = doc.get("routing") if isinstance(doc.get("routing"), dict) else {}
    tasks = routing.get("tasks") if isinstance(routing.get("tasks"), dict) else {}
    chain = routing.get("chain_fallback") if isinstance(routing.get("chain_fallback"), list) else []

    candidates: list[tuple[str, str]] = []

    def add_candidate(provider_id: str, model_override: str = "") -> None:
        candidate = (str(provider_id or "").strip(), str(model_override or "").strip())
        if candidate[0] and candidate not in candidates:
            candidates.append(candidate)

    primary = str(tasks.get(task_name) or "").strip()
    if primary:
        add_candidate(primary)
    task_backups = routing.get("task_backups") if isinstance(routing.get("task_backups"), dict) else {}
    task_backup_models = (
        routing.get("task_backup_models") if isinstance(routing.get("task_backup_models"), dict) else {}
    )
    add_candidate(task_backups.get(task_name), task_backup_models.get(task_name))
    from pallas.product.llm.task_routing import task_route_tier

    tier = task_route_tier(task_name)
    tier_backups = routing.get("tier_backups") if isinstance(routing.get("tier_backups"), dict) else {}
    tier_backup_models = (
        routing.get("tier_backup_models") if isinstance(routing.get("tier_backup_models"), dict) else {}
    )
    if tier:
        add_candidate(tier_backups.get(tier), tier_backup_models.get(tier))
    for item in chain:
        pid = str(item or "").strip()
        add_candidate(pid)
    if not candidates:
        for row in doc.get("providers") or []:
            if isinstance(row, dict) and str(row.get("id") or "").strip():
                add_candidate(str(row["id"]).strip())
                break

    out: list[ResolvedLlmEndpoint] = []
    for pid, model_override in candidates:
        row = find_provider(pid, doc=doc)
        if row is None:
            continue
        if row.get("enabled", True) is False:
            continue
        base_url = resolve_provider_base_url(row)
        model = model_override or provider_task_model(row, task_name)
        kind = str(row.get("kind") or "remote").strip().lower() or "remote"
        if kind == "local":
            from pallas.product.llm.local_routing_store import load_local_routing_document, resolve_local_task_model

            local_doc = load_local_routing_document()
            local_model = resolve_local_task_model(task_name)
            if local_doc.get("local_multi_model_enabled") and local_model:
                model = local_model
            elif not model and local_model:
                model = local_model
            elif not model:
                model = str(local_doc.get("llm_model") or "").strip()
        if not base_url or not model:
            continue
        api_keys = tuple(resolve_provider_api_keys(row))
        out.append(
            ResolvedLlmEndpoint(
                provider_id=pid,
                base_url=base_url,
                api_key=api_keys[0] if api_keys else "",
                model=model,
                kind=kind,
                capabilities=tuple(provider_capabilities(row)),
                model_effort=provider_model_effort(row),
                request_method=provider_request_method(row),
                api_keys=api_keys,
            )
        )
    return out


def resolve_endpoint_for_task(task: str = "llm_chat") -> ResolvedLlmEndpoint | None:
    candidates = resolve_endpoint_candidates_for_task(task)
    return candidates[0] if candidates else None


def bot_providers_configured(*, task: str = "llm_chat") -> bool:
    endpoint = resolve_endpoint_for_task(task)
    return endpoint is not None and bool(endpoint.base_url and endpoint.model)
