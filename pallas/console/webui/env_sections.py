"""WebUI 通用配置各段注册与读写。"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from pallas.core.foundation.config.dotenv import env_value_to_str, upsert_env_dotenv_items
from pallas.core.foundation.paths import PACKAGE_ROOT


@lru_cache(maxsize=1)
def _message_scrub_models() -> tuple[type[BaseModel], Any]:
    mod = importlib.import_module("pallas.product.message_scrub.config")
    return mod.MessageScrubConfig, mod.get_message_scrub_config


def _field_kind_from_annotation(ann: Any) -> str:
    from .field_meta import field_kind_from_annotation as kind_from_ann

    return kind_from_ann(ann)


def _jsonable_value(v: Any) -> Any:
    if v is PydanticUndefined:
        return None
    if isinstance(v, BaseModel):
        return v.model_dump(mode="python")
    if isinstance(v, dict):
        return {str(k): _jsonable_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_jsonable_value(x) for x in v]
    if isinstance(v, (set, tuple)):
        return [_jsonable_value(x) for x in v]
    return v


@dataclass(frozen=True)
class WebuiEnvSection:
    id: str
    title: str
    module_label: str
    model_cls: type[BaseModel]
    read_current: Any
    field_to_env: dict[str, str]
    skip_fields: frozenset[str]


def _message_scrub_section() -> WebuiEnvSection:
    msg_cfg_cls, get_msg_cfg = _message_scrub_models()
    field_to_env = {
        "inbound_filter_substrings": "PALLAS_INBOUND_FILTER_SUBSTRINGS",
        "scrub_lexicon_path": "PALLAS_SCRUB_LEXICON_PATH",
        "scrub_lexicon_extra": "PALLAS_SCRUB_LEXICON_EXTRA",
        "scrub_review_providers": "PALLAS_SCRUB_REVIEW_PROVIDERS",
        "scrub_api_url": "PALLAS_SCRUB_API_URL",
        "inbound_filter_api_url": "PALLAS_INBOUND_FILTER_API_URL",
        "inbound_filter_api_key": "PALLAS_INBOUND_FILTER_API_KEY",
        "inbound_filter_api_timeout_sec": "PALLAS_INBOUND_FILTER_API_TIMEOUT_SEC",
        "inbound_filter_api_fail_open": "PALLAS_INBOUND_FILTER_API_FAIL_OPEN",
        "scrub_baidu_api_key": "PALLAS_SCRUB_BAIDU_API_KEY",
        "scrub_baidu_secret_key": "PALLAS_SCRUB_BAIDU_SECRET_KEY",
        "scrub_baidu_censor_url": "PALLAS_SCRUB_BAIDU_CENSOR_URL",
        "scrub_baidu_strategy_id": "PALLAS_SCRUB_BAIDU_STRATEGY_ID",
        "scrub_baidu_block_suspected": "PALLAS_SCRUB_BAIDU_BLOCK_SUSPECTED",
    }
    return WebuiEnvSection(
        id="message_scrub",
        title="消息审查",
        module_label="pallas.product.message_scrub",
        model_cls=msg_cfg_cls,
        read_current=get_msg_cfg,
        field_to_env=field_to_env,
        skip_fields=frozenset({"scrub_review_providers_key_present"}),
    )


def clear_webui_env_sections_cache() -> None:
    """供测试或热重载场景清空段注册缓存。"""
    global _sections_cache
    _sections_cache = None


def field_to_env_uppercase_keys(model_cls: type[BaseModel]) -> dict[str, str]:
    """与插件配置 PUT 一致：环境变量键为字段名的全大写形式。"""
    return {name: name.upper() for name in model_cls.model_fields}


def _control_plane_section() -> WebuiEnvSection:
    from pallas.product.control_plane.webui_config import ControlPlaneWebuiConfig, get_control_plane_webui_config

    return WebuiEnvSection(
        id="control_plane",
        title="多机协同",
        module_label="pallas.product.control_plane",
        model_cls=ControlPlaneWebuiConfig,
        read_current=get_control_plane_webui_config,
        field_to_env={
            "enabled": "PALLAS_CONTROL_PLANE_ENABLED",
            "bootstrap_url": "PALLAS_CONTROL_PLANE_BOOTSTRAP_URL",
            "instance_secret": "PALLAS_INSTANCE_SECRET",
            "federate_id": "PALLAS_FEDERATE_ID",
            "federate_ingress_enabled": "PALLAS_FEDERATE_INGRESS_ENABLED",
            "federate_redis_prefix": "PALLAS_FEDERATE_REDIS_PREFIX",
            "coord_redis_url": "PALLAS_FEDERATE_COORD_REDIS_URL",
        },
        skip_fields=frozenset(),
    )


def _ingress_fanout_section() -> WebuiEnvSection:
    from pallas.core.platform.ingress.config import IngressFanoutConfig, get_ingress_fanout_config

    return WebuiEnvSection(
        id="ingress_fanout",
        title="全员同响口令",
        module_label="pallas.core.platform.ingress",
        model_cls=IngressFanoutConfig,
        read_current=get_ingress_fanout_config,
        field_to_env={"greeting_fanout_texts": "PALLAS_INGRESS_FANOUT_GREETING"},
        skip_fields=frozenset(),
    )


_INGRESS_DISPATCH_SKIP = frozenset({
    "matcher_dispatch_overload_threshold",
    "route_index_strict",
    "lane_acquire_timeout_sec",
    "lane_wait_overload_ms",
    "lane_busy_reply",
    "lane_command",
    "lane_chat",
    "lane_storage",
    "lane_remote",
    "send_queue_workers",
    "send_queue_max_depth",
    "send_queue_min_interval_ms",
    "send_queue_enqueue_timeout_sec",
})


def _ingress_dispatch_section() -> WebuiEnvSection:
    from pallas.core.platform.ingress.dispatch_runtime_config import (
        IngressDispatchRuntimeConfig,
        get_ingress_dispatch_runtime_config,
    )

    return WebuiEnvSection(
        id="ingress_dispatch",
        title="消息处理与发送",
        module_label="pallas.core.platform.ingress",
        model_cls=IngressDispatchRuntimeConfig,
        read_current=get_ingress_dispatch_runtime_config,
        field_to_env={
            "matcher_dispatch_enabled": "PALLAS_MATCHER_DISPATCH_ENABLED",
            "matcher_dispatch_overload_threshold": "PALLAS_MATCHER_DISPATCH_OVERLOAD_THRESHOLD",
            "route_index_enabled": "PALLAS_ROUTE_INDEX_ENABLED",
            "route_index_strict": "PALLAS_ROUTE_INDEX_STRICT",
            "dispatch_lanes_enabled": "PALLAS_DISPATCH_LANES_ENABLED",
            "lane_acquire_timeout_sec": "PALLAS_LANE_ACQUIRE_TIMEOUT_SEC",
            "lane_wait_overload_ms": "PALLAS_LANE_WAIT_OVERLOAD_MS",
            "lane_busy_reply": "PALLAS_LANE_BUSY_REPLY",
            "lane_command": "PALLAS_LANE_COMMAND",
            "lane_chat": "PALLAS_LANE_CHAT",
            "lane_storage": "PALLAS_LANE_STORAGE",
            "lane_remote": "PALLAS_LANE_REMOTE",
            "send_queue_enabled": "PALLAS_SEND_QUEUE_ENABLED",
            "send_queue_workers": "PALLAS_SEND_QUEUE_WORKERS",
            "send_queue_max_depth": "PALLAS_SEND_QUEUE_MAX_DEPTH",
            "send_queue_min_interval_ms": "PALLAS_SEND_QUEUE_MIN_INTERVAL_MS",
            "send_queue_enqueue_timeout_sec": "PALLAS_SEND_QUEUE_ENQUEUE_TIMEOUT_SEC",
        },
        skip_fields=_INGRESS_DISPATCH_SKIP,
    )


def _mail_section() -> WebuiEnvSection:
    from pallas.core.shared.utils.mail import SmtpConfig, get_smtp_config

    return WebuiEnvSection(
        id="mail",
        title="邮件发送（SMTP）",
        module_label="pallas.core.shared.utils.mail",
        model_cls=SmtpConfig,
        read_current=get_smtp_config,
        field_to_env={
            "smtp_user": "PALLAS_SMTP_USER",
            "smtp_password": "PALLAS_SMTP_PASSWORD",
            "smtp_server": "PALLAS_SMTP_SERVER",
            "smtp_port": "PALLAS_SMTP_PORT",
        },
        skip_fields=frozenset(),
    )


def _llm_section() -> WebuiEnvSection:
    from pallas.product.llm.webui_config import LlmWebuiConfig, get_llm_webui_config

    return WebuiEnvSection(
        id="llm",
        title="智能对话与 AI 服务",
        module_label="pallas.product.llm",
        model_cls=LlmWebuiConfig,
        read_current=get_llm_webui_config,
        field_to_env={
            "ai_server_host": "AI_SERVER_HOST",
            "ai_server_port": "AI_SERVER_PORT",
            "llm_chat_enabled": "LLM_CHAT_ENABLED",
            "llm_repeater_mode": "LLM_REPEATER_MODE",
            "llm_polish_lite_sample_rate": "LLM_POLISH_LITE_SAMPLE_RATE",
            "llm_governance_enabled": "LLM_GOVERNANCE_ENABLED",
            "llm_session_enabled": "LLM_SESSION_ENABLED",
            "llm_tools_enabled": "LLM_TOOLS_ENABLED",
            "llm_chat_max_concurrency": "LLM_CHAT_MAX_CONCURRENCY",
            "llm_repeater_group_cooldown_sec": "LLM_REPEATER_GROUP_COOLDOWN_SEC",
            "llm_repeater_max_inflight": "LLM_REPEATER_MAX_INFLIGHT",
            "llm_repeater_global_rpm": "LLM_REPEATER_GLOBAL_RPM",
            "llm_repeater_feedback_enabled": "LLM_REPEATER_FEEDBACK_ENABLED",
            "llm_repeater_bias_enabled": "LLM_REPEATER_BIAS_ENABLED",
            "llm_repeater_writeback_enabled": "LLM_REPEATER_WRITEBACK_ENABLED",
            "conversation_feature_level": "CONVERSATION_FEATURE_LEVEL",
            "llm_reply_gate_enabled": "LLM_REPLY_GATE_ENABLED",
            "llm_chat_queue_merge": "LLM_CHAT_QUEUE_MERGE",
            "llm_output_filter_enabled": "LLM_OUTPUT_FILTER_ENABLED",
            "llm_output_filter_chat_hard_phrases": "LLM_OUTPUT_FILTER_CHAT_HARD_PHRASES",
            "llm_output_filter_chat_soft_phrases": "LLM_OUTPUT_FILTER_CHAT_SOFT_PHRASES",
            "llm_output_filter_polish_lite_hard_phrases": "LLM_OUTPUT_FILTER_POLISH_LITE_HARD_PHRASES",
            "llm_output_filter_polish_lite_soft_phrases": "LLM_OUTPUT_FILTER_POLISH_LITE_SOFT_PHRASES",
            "llm_memory_rag_enabled": "LLM_MEMORY_RAG_ENABLED",
            "llm_vector_retrieve": "LLM_VECTOR_RETRIEVE",
            "llm_embedding_model": "LLM_EMBEDDING_MODEL",
            "llm_memory_auto_episode_enabled": "LLM_MEMORY_AUTO_EPISODE_ENABLED",
            "llm_knowledge_file_ingest_enabled": "LLM_KNOWLEDGE_FILE_INGEST_ENABLED",
            "llm_relationship_notes_enabled": "LLM_RELATIONSHIP_NOTES_ENABLED",
        },
        skip_fields=frozenset(),
    )


def _arknights_kb_section() -> WebuiEnvSection:
    from pallas.product.arknights_kb.config import ArknightsKbConfig, get_arknights_kb_config

    return WebuiEnvSection(
        id="arknights_kb",
        title="方舟知识库",
        module_label="pallas.product.arknights_kb",
        model_cls=ArknightsKbConfig,
        read_current=get_arknights_kb_config,
        field_to_env={
            "arknights_kb_enabled": "ARKNIGHTS_KB_ENABLED",
            "arknights_kb_auto_sync": "ARKNIGHTS_KB_AUTO_SYNC",
        },
        skip_fields=frozenset(),
    )


def _base_section_by_id(section_id: str) -> WebuiEnvSection | None:
    builders: dict[str, Any] = {
        "mail": _mail_section,
        "llm": _llm_section,
        "arknights_kb": _arknights_kb_section,
    }
    if (PACKAGE_ROOT / "product" / "control_plane" / "webui_config.py").is_file():
        builders["control_plane"] = _control_plane_section
    if (PACKAGE_ROOT / "core" / "platform" / "ingress" / "config.py").is_file():
        builders["ingress_fanout"] = _ingress_fanout_section
    if (PACKAGE_ROOT / "core" / "platform" / "ingress" / "dispatch_runtime_config.py").is_file():
        builders["ingress_dispatch"] = _ingress_dispatch_section
    from pallas.product.message_scrub.config import is_message_scrub_enabled

    if (PACKAGE_ROOT / "product" / "message_scrub" / "config.py").is_file() and is_message_scrub_enabled():
        builders["message_scrub"] = _message_scrub_section
    builder = builders.get(section_id)
    return builder() if builder is not None else None


_sections_cache: tuple[WebuiEnvSection, ...] | None = None


def _registered_sections() -> tuple[WebuiEnvSection, ...]:
    global _sections_cache
    if _sections_cache is not None:
        return _sections_cache
    parts: list[WebuiEnvSection] = [
        _llm_section(),
        _arknights_kb_section(),
    ]
    _sections_cache = tuple(parts)
    return _sections_cache


def list_webui_env_sections() -> list[dict[str, str]]:
    """通用配置页已移除；段 payload 仍经 ``webui_env_section_payload`` 供 AI 内嵌与插件聚合。"""
    return []


_REMOVED_FROM_COMMON_CONFIG_LIST = frozenset({
    "mail",
    "message_scrub",
    "ingress_fanout",
    "ingress_dispatch",
    "control_plane",
    "corpus_federation",
})


def _resolve_webui_env_section(section_id: str) -> WebuiEnvSection:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    sid = canonical_plugin_package((section_id or "").strip())
    base = _base_section_by_id(sid)
    if base is not None:
        return base
    for s in _registered_sections():
        if s.id == sid:
            return s
    raise ValueError(f"未知 common-config: {section_id}")


def get_webui_env_section(section_id: str) -> WebuiEnvSection:
    sid = (section_id or "").strip()
    if sid in _REMOVED_FROM_COMMON_CONFIG_LIST:
        raise ValueError(f"{sid} 已迁至 pb_core 插件配置页")
    from .control_plane_section import CONTROL_PLANE_SECTION_ID
    from .corpus_federation_section import CORPUS_FEDERATION_SECTION_ID

    if sid in (CORPUS_FEDERATION_SECTION_ID, CONTROL_PLANE_SECTION_ID):
        raise ValueError(f"{sid} 已迁至 pb_core 插件配置页")
    return _resolve_webui_env_section(sid)


def webui_env_section_payload(
    section_id: str,
    *,
    current_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """GET 默认读进程内配置；PUT 后应传 ``validated``，与刚写入 ``.env`` 的值一致。"""
    from .control_plane_section import CONTROL_PLANE_SECTION_ID
    from .corpus_federation_section import CORPUS_FEDERATION_SECTION_ID
    from .service_gateways_section import SERVICE_GATEWAYS_SECTION_ID

    if section_id == CONTROL_PLANE_SECTION_ID:
        from .control_plane_section import control_plane_payload

        return control_plane_payload(current_values=current_values)
    if section_id == CORPUS_FEDERATION_SECTION_ID:
        from .corpus_federation_section import corpus_federation_payload

        return corpus_federation_payload(current_values=current_values)
    if section_id == SERVICE_GATEWAYS_SECTION_ID:
        from .service_gateways_section import service_gateways_payload

        return service_gateways_payload(current_values=current_values)
    if section_id == "llm":
        from pallas.core.foundation.config.repo_settings import purge_misplaced_ai_env_keys_from_webui

        purge_misplaced_ai_env_keys_from_webui()
    s = _resolve_webui_env_section(section_id)
    cfg_obj = s.read_current()
    fields: list[dict[str, Any]] = []
    for key, f in s.model_cls.model_fields.items():
        if key in s.skip_fields:
            continue
        env_key = s.field_to_env.get(key)
        if not env_key:
            continue
        if current_values is not None:
            cur = current_values.get(key, getattr(cfg_obj, key, f.default))
        else:
            cur = getattr(cfg_obj, key, f.default)
        default_value = None if f.default is PydanticUndefined else f.default
        from .field_meta import field_meta_for_model_field

        fields.append(
            field_meta_for_model_field(
                key=key,
                field=f,
                env_key=env_key,
                cur=cur,
                default_value=default_value,
            )
        )
    base: dict[str, Any] = {
        "plugin": s.id,
        "module": s.module_label,
        "fields": fields,
    }
    if section_id == "llm":
        base.update({"llm_model_admin": True})
    elif section_id == "ingress_dispatch":
        base.update(_ingress_dispatch_payload_extras())
    return base


def _ingress_dispatch_payload_extras() -> dict[str, Any]:
    return {
        "field_groups": [
            {
                "id": "matcher",
                "title": "无关消息预筛",
                "field_names": [
                    "matcher_dispatch_enabled",
                    "matcher_dispatch_overload_threshold",
                ],
            },
            {
                "id": "route_index",
                "title": "口令快速定位",
                "field_names": ["route_index_enabled", "route_index_strict"],
            },
            {
                "id": "lanes",
                "title": "同时处理上限",
                "field_names": [
                    "dispatch_lanes_enabled",
                    "lane_acquire_timeout_sec",
                    "lane_wait_overload_ms",
                    "lane_busy_reply",
                    "lane_command",
                    "lane_chat",
                    "lane_storage",
                    "lane_remote",
                ],
            },
            {
                "id": "send_queue",
                "title": "发送排队",
                "field_names": [
                    "send_queue_enabled",
                    "send_queue_workers",
                    "send_queue_max_depth",
                    "send_queue_min_interval_ms",
                    "send_queue_enqueue_timeout_sec",
                ],
            },
        ],
    }


def apply_webui_env_section_patch(section_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    from .control_plane_section import CONTROL_PLANE_SECTION_ID, apply_control_plane_patch
    from .corpus_federation_section import CORPUS_FEDERATION_SECTION_ID, apply_corpus_federation_patch
    from .service_gateways_section import (
        SERVICE_GATEWAYS_SECTION_ID,
        apply_service_gateways_patch,
    )

    if section_id == CONTROL_PLANE_SECTION_ID:
        return apply_control_plane_patch(patch)
    if section_id == CORPUS_FEDERATION_SECTION_ID:
        return apply_corpus_federation_patch(patch)
    if section_id == SERVICE_GATEWAYS_SECTION_ID:
        return apply_service_gateways_patch(patch)
    s = _resolve_webui_env_section(section_id)
    current = s.read_current().model_dump(mode="python")
    allowed = set(s.field_to_env.keys()) - set(s.skip_fields)
    for k in patch:
        if k not in allowed:
            raise ValueError(f"未知配置项: {k}")
    merged = {**current, **patch}
    validated = s.model_cls(**merged).model_dump(mode="python")
    items = {s.field_to_env[k]: env_value_to_str(validated[k]) for k in patch}
    upsert_env_dotenv_items(items)
    if section_id == "llm":
        from pallas.core.foundation.config.repo_settings import purge_misplaced_ai_env_keys_from_webui

        purge_misplaced_ai_env_keys_from_webui()
    if section_id == "message_scrub":
        try:
            from pallas.product.message_scrub import reload_message_scrub_caches

            reload_message_scrub_caches()
        except Exception:
            pass
    if section_id == "ingress_fanout":
        try:
            from pallas.core.platform.ingress.config import clear_ingress_fanout_config_cache

            clear_ingress_fanout_config_cache()
        except Exception:
            pass
    elif section_id == "ingress_dispatch":
        try:
            from pallas.core.platform.ingress.dispatch_lanes import clear_dispatch_lanes_cache
            from pallas.core.platform.ingress.dispatch_runtime_config import clear_ingress_dispatch_runtime_config_cache
            from pallas.core.platform.ingress.route_index import clear_route_index_cache

            clear_ingress_dispatch_runtime_config_cache()
            clear_dispatch_lanes_cache()
            clear_route_index_cache()
        except Exception:
            pass
    elif section_id == "llm":
        try:
            from pallas.product.llm.config import clear_llm_config_cache

            clear_llm_config_cache()
        except Exception:
            pass
        if "ai_server_host" in patch or "ai_server_port" in patch:
            try:
                from pallas.console.webui.ai_install_writeback import (
                    sync_extension_base_url_from_ai_server,
                )

                sync_extension_base_url_from_ai_server(
                    str(validated.get("ai_server_host") or ""),
                    validated.get("ai_server_port") or "",
                )
            except Exception:
                pass
    else:
        plugin_module = s.module_label if s.module_label.startswith(("pallas.", "packages.")) else ""
        if plugin_module:
            try:
                from .registry import reload_plugin_config

                reload_plugin_config(plugin_module)
            except Exception:
                pass
    return webui_env_section_payload(section_id, current_values=validated)


_COMMON_CONFIG_RAW_UNSUPPORTED = frozenset({
    "corpus_federation",
    "service_gateways",
    "control_plane",
    "mail",
    "message_scrub",
    "ingress_fanout",
    "ingress_dispatch",
})


def common_config_section_supports_raw(section_id: str) -> bool:
    sid = (section_id or "").strip()
    if sid in _COMMON_CONFIG_RAW_UNSUPPORTED:
        return False
    try:
        _resolve_webui_env_section(sid)
    except ValueError:
        return False
    return True


def webui_env_section_raw_toml(section_id: str) -> str:
    import json

    if not common_config_section_supports_raw(section_id):
        raise ValueError(f"{section_id} 不支持 Raw TOML 编辑")
    s = _resolve_webui_env_section(section_id)
    from pallas.core.foundation.config.repo_settings import _load_webui_json_upper

    env = _load_webui_json_upper()
    lines = [f"# common-config: {section_id}", f"# module: {s.module_label}", "", "[env]"]
    allowed = set(s.field_to_env.keys()) - set(s.skip_fields)
    for field_key in sorted(allowed):
        env_key = s.field_to_env[field_key]
        if env_key in env:
            lines.append(f"{env_key} = {json.dumps(str(env[env_key]), ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines)


def apply_webui_env_section_raw_toml(section_id: str, text: str) -> dict[str, Any]:
    import tomllib

    from .plugin_api import normalize_patch_value

    if not common_config_section_supports_raw(section_id):
        raise ValueError(f"{section_id} 不支持 Raw TOML 编辑")
    raw = (text or "").strip()
    if not raw:
        raise ValueError("TOML 内容为空")
    try:
        doc = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"TOML 解析失败: {exc}") from exc
    env_block = doc.get("env") if isinstance(doc.get("env"), dict) else doc
    if not isinstance(env_block, dict):
        raise ValueError("缺少 [env] 表")
    s = _resolve_webui_env_section(section_id)
    reverse = {str(v).upper(): k for k, v in s.field_to_env.items()}
    allowed = set(s.field_to_env.keys()) - set(s.skip_fields)
    patch: dict[str, Any] = {}
    for env_key, value in env_block.items():
        field_key = reverse.get(str(env_key).upper())
        if field_key and field_key in allowed:
            patch[field_key] = normalize_patch_value(s.model_cls.model_fields[field_key], value)
    if not patch:
        raise ValueError("没有可识别的配置键")
    return apply_webui_env_section_patch(section_id, patch)
