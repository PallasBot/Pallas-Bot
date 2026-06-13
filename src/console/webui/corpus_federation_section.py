"""WebUI「通用配置 → 语料联邦」（Phase 1：local + community）。"""

from __future__ import annotations

from typing import Any

from pydantic_core import PydanticUndefined

from src.console.webui.field_help import normalize_field_description
from src.features.corpus.reply_perf_config import CorpusReplyPerfConfig, get_corpus_reply_perf_config
from src.features.corpus.webui_config import CorpusFederationWebuiConfig, get_corpus_federation_webui_config
from src.foundation.config.dotenv import env_value_to_str
from src.foundation.config.repo_settings import upsert_repo_settings_items

CORPUS_FEDERATION_SECTION_ID = "corpus_federation"
CORPUS_FEDERATION_TITLE = "语料联邦"

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

_FIELD_LABELS: dict[str, str] = {
    "merge_order": "接话查找顺序",
    "merge_strategy": "重复句如何合并",
    "community_enabled": "使用共享语料",
    "auto_enroll": "自动登记语料凭证",
    "community_contribute": "上传本机新回复",
    "corpus_backfill_enabled": "同步历史语料到共享池",
    "corpus_backfill_batch_size": "每轮同步条数",
    "corpus_backfill_interval_sec": "同步间隔（秒）",
    "corpus_backfill_max_per_minute": "同步限速（次/分钟）",
    "remote_find_enabled": "本机未命中时查共享池",
    "community_api_base": "共享语料服务地址",
    "community_token": "共享语料访问口令",
    "reply_messages_cap": "接话历史条数上限",
    "reply_answers_cap": "接话候选条数上限",
    "find_cache_ttl_sec": "查询缓存保留秒数",
    "find_cache_max": "查询缓存条数上限",
    "reply_snapshot_ttl_sec": "接话快照保留秒数",
    "reply_snapshot_max": "接话快照条数上限",
}


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
    from src.console.webui.field_meta import field_kind_from_annotation, literal_choices

    ann = f.annotation
    choices = literal_choices(ann)
    row: dict[str, Any] = {
        "name": key,
        "label": _FIELD_LABELS.get(key, ""),
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
        from src.console.webui.field_help import field_help

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
    return row


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
        "module": "src.features.corpus",
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
        from src.features.corpus.config import clear_corpus_config_cache

        clear_corpus_config_cache()
    except Exception:
        pass
    if "remote_find_enabled" in patch or set(_REPLY_PERF_FIELD_NAMES) & set(patch):
        try:
            import asyncio

            from src.features.corpus.find_cache import invalidate_find_cache

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

            from src.features.corpus.prefetch import reload_corpus_prefetch_workers

            try:
                asyncio.get_running_loop().create_task(reload_corpus_prefetch_workers())
            except RuntimeError:
                asyncio.run(reload_corpus_prefetch_workers())
        except Exception:
            pass
    if set(_REPLY_PERF_FIELD_NAMES) & set(patch):
        try:
            from src.features.corpus.reply_perf_config import clear_corpus_reply_perf_config_cache

            clear_corpus_reply_perf_config_cache()
        except Exception:
            pass
        try:
            import asyncio

            from src.foundation.db.repository_pg import clear_reply_query_snapshot_cache

            coro = clear_reply_query_snapshot_cache(None)
            try:
                asyncio.get_running_loop().create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception:
            pass
    if set(_BACKFILL_FIELD_NAMES) & set(patch):
        try:
            import asyncio

            from src.features.corpus.backfill_scheduler import reload_corpus_backfill_job

            try:
                asyncio.get_running_loop().create_task(reload_corpus_backfill_job())
            except RuntimeError:
                asyncio.run(reload_corpus_backfill_job())
        except Exception:
            pass
    try:
        from src.foundation.db.context_repo_access import invalidate_shared_context_repository

        invalidate_shared_context_repository()
    except Exception:
        pass
    try:
        from nonebot import logger

        logger.info("corpus_federation: WebUI 已写入配置，语料相关项已热重载")
    except Exception as e:
        from nonebot import logger

        logger.warning("corpus_federation hot reload failed: {}", e)
    return corpus_federation_payload(current_values={**validated, **validated_perf})
