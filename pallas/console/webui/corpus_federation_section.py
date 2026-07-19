"""WebUI 社区共享接话库配置段。"""

from __future__ import annotations

from typing import Any

from pydantic_core import PydanticUndefined

from pallas.console.webui.field_help import normalize_field_description
from pallas.core.foundation.config.dotenv import env_value_to_str
from pallas.core.foundation.config.repo_settings import upsert_repo_settings_items
from pallas.product.corpus.reply_perf_config import CorpusReplyPerfConfig, get_corpus_reply_perf_config
from pallas.product.corpus.webui_config import CorpusFederationWebuiConfig, get_corpus_federation_webui_config

CORPUS_FEDERATION_SECTION_ID = "corpus_federation"
CORPUS_FEDERATION_TITLE = "社区共享接话库"

# Phase 1 仅暴露已接入项；fed / on_remote_failure 等 Phase 2 不在 WebUI 展示。
_PHASE1_FIELD_NAMES: tuple[str, ...] = (
    "merge_order",
    "merge_strategy",
    "community_enabled",
    "auto_enroll",
    "community_contribute",
    "remote_find_enabled",
    "community_api_base",
    "community_token",
)

_REPLY_PERF_FIELD_NAMES: tuple[str, ...] = (
    "reply_messages_cap",
    "reply_answers_cap",
    "find_cache_ttl_sec",
    "find_cache_max",
    "reply_snapshot_ttl_sec",
    "reply_snapshot_max",
)

_BACKFILL_FIELD_NAMES: tuple[str, ...] = (
    "corpus_backfill_enabled",
    "corpus_backfill_batch_size",
    "corpus_backfill_interval_sec",
    "corpus_backfill_max_per_minute",
)

_WEBUI_FIELD_NAMES: tuple[str, ...] = _PHASE1_FIELD_NAMES + _BACKFILL_FIELD_NAMES + _REPLY_PERF_FIELD_NAMES

_FIELD_TO_ENV: dict[str, str] = {
    "merge_order": "PALLAS_CORPUS_MERGE_ORDER",
    "merge_strategy": "PALLAS_CORPUS_MERGE_STRATEGY",
    "community_enabled": "PALLAS_CORPUS_COMMUNITY_ENABLED",
    "auto_enroll": "PALLAS_CORPUS_AUTO_ENROLL",
    "community_contribute": "PALLAS_CORPUS_COMMUNITY_CONTRIBUTE",
    "corpus_backfill_enabled": "PALLAS_CORPUS_BACKFILL_ENABLED",
    "corpus_backfill_batch_size": "PALLAS_CORPUS_BACKFILL_BATCH_SIZE",
    "corpus_backfill_interval_sec": "PALLAS_CORPUS_BACKFILL_INTERVAL_SEC",
    "corpus_backfill_max_per_minute": "PALLAS_CORPUS_BACKFILL_MAX_PER_MINUTE",
    "remote_find_enabled": "PALLAS_CORPUS_REMOTE_FIND_ENABLED",
    "community_api_base": "PALLAS_CORPUS_COMMUNITY_API_BASE",
    "community_token": "PALLAS_CORPUS_TOKEN",
}

_PERF_FIELD_TO_ENV: dict[str, str] = {
    "reply_messages_cap": "PALLAS_CORPUS_REPLY_MESSAGES_CAP",
    "reply_answers_cap": "PALLAS_CORPUS_REPLY_ANSWERS_CAP",
    "find_cache_ttl_sec": "PALLAS_CORPUS_FIND_CACHE_SEC",
    "find_cache_max": "PALLAS_CORPUS_FIND_CACHE_MAX",
    "reply_snapshot_ttl_sec": "PALLAS_CORPUS_REPLY_SNAPSHOT_SEC",
    "reply_snapshot_max": "PALLAS_CORPUS_REPLY_SNAPSHOT_MAX",
}

_FIELD_TO_ENV_ALL: dict[str, str] = {**_FIELD_TO_ENV, **_PERF_FIELD_TO_ENV}

_TRI_CHOICES = ["auto", "true", "false"]
_REMOTE_FIND_CHOICES = ["auto", "false", "prefetch", "sync"]
_MERGE_ORDER_CHOICES = ["local,community", "local"]


def _jsonable(v: Any) -> Any:
    if v is PydanticUndefined:
        return None
    return v


def _community_enabled_bool(cur: Any) -> bool:
    if cur is True or cur == "true":
        return True
    if cur is False or cur == "false":
        return False
    return False


def _field_row(key: str, cur: Any, *, model_fields: dict) -> dict[str, Any]:
    f = model_fields[key]
    default_value = None if f.default is PydanticUndefined else f.default
    from pallas.console.webui.enum_labels import attach_choice_labels
    from pallas.console.webui.field_labels import webui_field_label
    from pallas.console.webui.field_meta import field_kind_from_annotation, literal_choices

    ann = f.annotation
    choices = literal_choices(ann)
    row: dict[str, Any] = {
        "name": key,
        "label": webui_field_label(key),
        "kind": field_kind_from_annotation(ann),
        "required": bool(f.is_required()),
        "description": normalize_field_description(str(f.description or "")),
        "env_key": _FIELD_TO_ENV_ALL.get(key, key.upper()),
        "default": _jsonable(default_value),
        "current": _jsonable(cur),
    }
    if choices is not None:
        row["choices"] = choices
    if key == "community_enabled":
        row["kind"] = "bool"
        from pallas.console.webui.field_help import field_help

        row["description"] = field_help(
            "是否从社区共享语料池读取回复",
            "开启后接话时可查本机语料之外的共享池；关闭则只用本机语料",
            "首次开启前请确认下方地址与口令已就绪",
        )
        row["current"] = _community_enabled_bool(cur)
    elif key == "merge_order":
        row["kind"] = "enum"
        row["choices"] = _MERGE_ORDER_CHOICES
        if row["current"] not in _MERGE_ORDER_CHOICES:
            row["current"] = _MERGE_ORDER_CHOICES[0]
    elif key == "remote_find_enabled":
        row["kind"] = "enum"
        row["choices"] = _REMOTE_FIND_CHOICES
        cur_s = str(cur).strip().lower() if cur is not None else "auto"
        if cur_s == "true":
            cur_s = "prefetch"
        if cur_s not in _REMOTE_FIND_CHOICES:
            cur_s = "auto"
        row["current"] = cur_s
    elif key in ("auto_enroll", "community_contribute"):
        row["kind"] = "enum"
        row["choices"] = _TRI_CHOICES
    elif key == "corpus_backfill_enabled":
        row["kind"] = "bool"
        row["current"] = cur is True or str(cur).strip().lower() in ("1", "true", "yes", "on")
    attach_choice_labels(row)
    return row


def schedule_corpus_backfill_reload() -> None:
    import asyncio

    from pallas.product.corpus.backfill_scheduler import reload_corpus_backfill_job

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(reload_corpus_backfill_job())


def corpus_federation_payload(*, current_values: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = get_corpus_federation_webui_config()
    perf = get_corpus_reply_perf_config()
    data = {**cfg.model_dump(mode="python"), **perf.model_dump(mode="python")}
    if current_values is not None:
        data = {**data, **current_values}
    fields = [
        _field_row(k, data.get(k), model_fields=CorpusFederationWebuiConfig.model_fields) for k in _PHASE1_FIELD_NAMES
    ]
    fields.extend(
        _field_row(k, data.get(k), model_fields=CorpusFederationWebuiConfig.model_fields) for k in _BACKFILL_FIELD_NAMES
    )
    fields.extend(
        _field_row(k, data.get(k), model_fields=CorpusReplyPerfConfig.model_fields) for k in _REPLY_PERF_FIELD_NAMES
    )
    return {
        "plugin": CORPUS_FEDERATION_SECTION_ID,
        "module": "pallas.product.corpus",
        "hot_reload": True,
        "fields": fields,
        "field_groups": [
            {
                "id": "merge",
                "title": "接话时查哪些语料",
                "field_names": ["merge_order", "merge_strategy"],
            },
            {
                "id": "community",
                "title": "社区共享语料",
                "field_names": [
                    "community_enabled",
                    "auto_enroll",
                    "community_contribute",
                    "remote_find_enabled",
                    "community_api_base",
                    "community_token",
                ],
            },
            {
                "id": "backfill",
                "title": "历史语料同步",
                "field_names": list(_BACKFILL_FIELD_NAMES),
            },
            {
                "id": "reply_perf",
                "title": "接话性能（一般无需改）",
                "field_names": list(_REPLY_PERF_FIELD_NAMES),
            },
        ],
    }


def _normalize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(patch)
    if "community_enabled" in out:
        v = out["community_enabled"]
        if isinstance(v, bool):
            out["community_enabled"] = "true" if v else "false"
    for key in _REPLY_PERF_FIELD_NAMES + (
        "corpus_backfill_batch_size",
        "corpus_backfill_interval_sec",
        "corpus_backfill_max_per_minute",
    ):
        if key in out:
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError) as e:
                raise ValueError(f"{key} 须为整数") from e
    return out


def apply_corpus_federation_patch(patch: dict[str, Any]) -> dict[str, Any]:
    patch = _normalize_patch(patch)
    current = get_corpus_federation_webui_config().model_dump(mode="python")
    current_perf = get_corpus_reply_perf_config().model_dump(mode="python")
    allowed = set(_WEBUI_FIELD_NAMES)
    for k in patch:
        if k not in allowed:
            raise ValueError(f"未知配置项: {k}")
    merged = {**current, **current_perf, **patch}
    validated = CorpusFederationWebuiConfig(**{
        k: merged[k] for k in _PHASE1_FIELD_NAMES + _BACKFILL_FIELD_NAMES
    }).model_dump(mode="python")
    validated_perf = CorpusReplyPerfConfig(**{k: merged[k] for k in _REPLY_PERF_FIELD_NAMES}).model_dump(mode="python")
    items = {_FIELD_TO_ENV[k]: env_value_to_str(validated[k]) for k in patch if k in _FIELD_TO_ENV}
    items.update({_PERF_FIELD_TO_ENV[k]: env_value_to_str(validated_perf[k]) for k in patch if k in _PERF_FIELD_TO_ENV})
    upsert_repo_settings_items(items)
    try:
        from pallas.product.corpus.config import clear_corpus_config_cache

        clear_corpus_config_cache()
    except Exception:
        pass
    if "remote_find_enabled" in patch or set(_REPLY_PERF_FIELD_NAMES) & set(patch):
        try:
            import asyncio

            from pallas.product.corpus.find_cache import invalidate_find_cache

            coro = invalidate_find_cache(None)
            try:
                asyncio.get_running_loop().create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception:
            pass
    if "remote_find_enabled" in patch:
        try:
            import asyncio

            from pallas.product.corpus.prefetch import reload_corpus_prefetch_workers

            try:
                asyncio.get_running_loop().create_task(reload_corpus_prefetch_workers())
            except RuntimeError:
                asyncio.run(reload_corpus_prefetch_workers())
        except Exception:
            pass
    if set(_REPLY_PERF_FIELD_NAMES) & set(patch):
        try:
            from pallas.product.corpus.reply_perf_config import clear_corpus_reply_perf_config_cache

            clear_corpus_reply_perf_config_cache()
        except Exception:
            pass
        try:
            import asyncio

            from pallas.core.foundation.db.repository_pg import clear_reply_query_snapshot_cache

            coro = clear_reply_query_snapshot_cache(None)
            try:
                asyncio.get_running_loop().create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception:
            pass
    if set(_BACKFILL_FIELD_NAMES) & set(patch):
        try:
            schedule_corpus_backfill_reload()
        except Exception:
            pass
    try:
        from pallas.core.foundation.db.context_repo_access import invalidate_shared_context_repository

        invalidate_shared_context_repository()
    except Exception:
        pass
    try:
        from nonebot import logger

        logger.info("corpus_federation: webui config saved, hot reloaded")
    except Exception as e:
        from nonebot import logger

        logger.warning("corpus_federation hot reload failed: {}", e)
    return corpus_federation_payload(current_values={**validated, **validated_perf})
