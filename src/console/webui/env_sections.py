"""在 WebUI「通用配置」中暴露的配置段：对应根目录 ``.env`` 的 Pydantic 模型。

- ``message_scrub``：显式 ``field_to_env``（与历史 ``PALLAS_*`` 键名一致）。
- ``cmd_perm``：命令权限覆盖（``PALLAS_COMMAND_PERMISSION_OVERRIDES``）。
- 若干 NoneBot 插件：字段名大写写入 ``.env``。

新增段：在 ``_registered_sections`` 中追加；插件段可用 ``_plugin_env_section_from_module``。
已使用 ``install_hot_reload_config`` 的插件会通过注册表读取当前值。
``ingress_fanout`` / ``repeater_learn`` 等 common 段保存后会清缓存并触发热重载钩子。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from importlib import util as importlib_util
from typing import Any

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from src.foundation.config.dotenv import env_value_to_str, upsert_env_dotenv_items
from src.foundation.paths import PROJECT_ROOT, SRC_ROOT


@lru_cache(maxsize=1)
def _message_scrub_models() -> tuple[type[BaseModel], Any]:
    path = SRC_ROOT / "features" / "message_scrub" / "config.py"
    name = "_pallas_webui_message_scrub_config"
    spec = importlib_util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"message_scrub 配置模块未找到: {path}")
    mod = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
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
        title="消息审查与入站过滤",
        module_label="src.features.message_scrub",
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


def _plugin_env_section_from_module(
    *,
    section_id: str,
    title: str,
    module_label: str,
    config_module: str,
) -> WebuiEnvSection | None:
    """从 ``*.config`` 加载 ``Config``；若已 ``install_hot_reload_config`` 则走注册表。"""
    try:
        mod = importlib.import_module(config_module)
    except ModuleNotFoundError:
        from nonebot import logger

        logger.warning("WebUI 通用配置段跳过：未找到配置模块 {}", config_module)
        return None
    cfg_cls = getattr(mod, "Config", None)
    if cfg_cls is None or not isinstance(cfg_cls, type) or not issubclass(cfg_cls, BaseModel):
        return None

    plugin_module = config_module.removesuffix(".config")

    def read_current() -> BaseModel:
        from nonebot import get_plugin_config

        from .registry import read_plugin_config

        return read_plugin_config(
            plugin_module,
            cfg_cls,
            fallback_getter=lambda: get_plugin_config(cfg_cls),
        )

    return WebuiEnvSection(
        id=section_id,
        title=title,
        module_label=module_label,
        model_cls=cfg_cls,
        read_current=read_current,
        field_to_env=field_to_env_uppercase_keys(cfg_cls),
        skip_fields=frozenset(),
    )


def _control_plane_section() -> WebuiEnvSection:
    from src.features.control_plane.webui_config import ControlPlaneWebuiConfig, get_control_plane_webui_config

    return WebuiEnvSection(
        id="control_plane",
        title="联邦控制",
        module_label="src.features.control_plane",
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
    from src.platform.ingress.config import IngressFanoutConfig, get_ingress_fanout_config

    return WebuiEnvSection(
        id="ingress_fanout",
        title="入站：全员同响口令",
        module_label="src.platform.ingress",
        model_cls=IngressFanoutConfig,
        read_current=get_ingress_fanout_config,
        field_to_env={"greeting_fanout_texts": "PALLAS_INGRESS_FANOUT_GREETING"},
        skip_fields=frozenset(),
    )


def _repeater_learn_section() -> WebuiEnvSection:
    from src.plugins.repeater.learn_runtime_config import (
        RepeaterLearnRuntimeConfig,
        get_repeater_learn_runtime_config,
    )

    field_to_env = {
        "learn_concurrency": "PALLAS_REPEATER_LEARN_CONCURRENCY",
        "learn_queue_max_size": "PALLAS_REPEATER_LEARN_QUEUE_SIZE",
    }
    return WebuiEnvSection(
        id="repeater_learn",
        title="复读：后台语料学习",
        module_label="src.plugins.repeater",
        model_cls=RepeaterLearnRuntimeConfig,
        read_current=get_repeater_learn_runtime_config,
        field_to_env=field_to_env,
        skip_fields=frozenset(),
    )


def _cmd_perm_section() -> WebuiEnvSection:
    from src.features.cmd_perm.config import CmdPermConfig, get_cmd_perm_config

    return WebuiEnvSection(
        id="cmd_perm",
        title="命令权限",
        module_label="src.features.cmd_perm",
        model_cls=CmdPermConfig,
        read_current=get_cmd_perm_config,
        field_to_env={"command_permission_overrides": "PALLAS_COMMAND_PERMISSION_OVERRIDES"},
        skip_fields=frozenset(),
    )


_sections_cache: tuple[WebuiEnvSection, ...] | None = None


def _registered_sections() -> tuple[WebuiEnvSection, ...]:
    global _sections_cache
    if _sections_cache is not None:
        return _sections_cache
    parts: list[WebuiEnvSection] = []
    parts.append(_cmd_perm_section())
    if (SRC_ROOT / "features" / "control_plane" / "webui_config.py").is_file():
        parts.append(_control_plane_section())
    if (SRC_ROOT / "platform" / "ingress" / "config.py").is_file():
        parts.append(_ingress_fanout_section())
    repeater_learn_cfg = PROJECT_ROOT / "src" / "plugins" / "repeater" / "learn_runtime_config.py"
    if repeater_learn_cfg.is_file():
        parts.append(_repeater_learn_section())
    from src.foundation.deploy_profile import message_scrub_webui_available

    if (SRC_ROOT / "features" / "message_scrub" / "config.py").is_file() and message_scrub_webui_available():
        parts.append(_message_scrub_section())
    parts.extend(
        s
        for s in (
            _plugin_env_section_from_module(
                section_id="pallas_webui",
                title="网页控制台",
                module_label="src.plugins.pallas_webui",
                config_module="src.plugins.pallas_webui.config",
            ),
            _plugin_env_section_from_module(
                section_id="pallas_protocol",
                title="QQ 协议端（NapCat 等）",
                module_label="src.plugins.pallas_protocol",
                config_module="src.plugins.pallas_protocol.config",
            ),
            _plugin_env_section_from_module(
                section_id="help",
                title="帮助菜单与样式",
                module_label="src.plugins.help",
                config_module="src.plugins.help.config",
            ),
        )
        if s is not None
    )
    _sections_cache = tuple(parts)
    return _sections_cache


_COMMON_CONFIG_SECTION_ORDER: tuple[str, ...] = (
    "cmd_perm",
    "control_plane",
    "corpus_federation",
    "community_stats",
    "ingress_fanout",
    "repeater_learn",
    "message_scrub",
    "service_gateways",
    "pallas_webui",
    "pallas_protocol",
    "help",
)


def list_webui_env_sections() -> list[dict[str, str]]:
    from .community_stats_section import COMMUNITY_STATS_SECTION_ID, COMMUNITY_STATS_TITLE
    from .control_plane_section import CONTROL_PLANE_SECTION_ID, CONTROL_PLANE_TITLE
    from .corpus_federation_section import CORPUS_FEDERATION_SECTION_ID, CORPUS_FEDERATION_TITLE
    from .service_gateways_section import (
        SERVICE_GATEWAYS_SECTION_ID,
        SERVICE_GATEWAYS_TITLE,
    )

    by_id: dict[str, dict[str, str]] = {s.id: {"id": s.id, "title": s.title} for s in _registered_sections()}
    by_id[CORPUS_FEDERATION_SECTION_ID] = {
        "id": CORPUS_FEDERATION_SECTION_ID,
        "title": CORPUS_FEDERATION_TITLE,
    }
    by_id[COMMUNITY_STATS_SECTION_ID] = {
        "id": COMMUNITY_STATS_SECTION_ID,
        "title": COMMUNITY_STATS_TITLE,
    }
    by_id[SERVICE_GATEWAYS_SECTION_ID] = {
        "id": SERVICE_GATEWAYS_SECTION_ID,
        "title": SERVICE_GATEWAYS_TITLE,
    }
    if CONTROL_PLANE_SECTION_ID in by_id:
        by_id[CONTROL_PLANE_SECTION_ID]["title"] = CONTROL_PLANE_TITLE

    ordered: list[dict[str, str]] = []
    seen: set[str] = set()
    for sid in _COMMON_CONFIG_SECTION_ORDER:
        row = by_id.get(sid)
        if row is None:
            continue
        ordered.append(row)
        seen.add(sid)
    for sid, row in by_id.items():
        if sid not in seen:
            ordered.append(row)
    return ordered


def get_webui_env_section(section_id: str) -> WebuiEnvSection:
    from .community_stats_section import COMMUNITY_STATS_SECTION_ID
    from .control_plane_section import CONTROL_PLANE_SECTION_ID
    from .corpus_federation_section import CORPUS_FEDERATION_SECTION_ID

    if section_id in (CORPUS_FEDERATION_SECTION_ID, CONTROL_PLANE_SECTION_ID, COMMUNITY_STATS_SECTION_ID):
        raise ValueError(f"{section_id} 使用专用 payload，勿走 WebuiEnvSection")
    sid = (section_id or "").strip()
    for s in _registered_sections():
        if s.id == sid:
            return s
    raise ValueError(f"未知 common-config: {section_id}")


def webui_env_section_payload(
    section_id: str,
    *,
    current_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """GET 默认读进程内配置；PUT 后应传 ``validated``，与刚写入 ``.env`` 的值一致。"""
    from .community_stats_section import COMMUNITY_STATS_SECTION_ID, community_stats_payload
    from .control_plane_section import CONTROL_PLANE_SECTION_ID, control_plane_payload
    from .corpus_federation_section import CORPUS_FEDERATION_SECTION_ID, corpus_federation_payload
    from .service_gateways_section import SERVICE_GATEWAYS_SECTION_ID, service_gateways_payload

    if section_id == CONTROL_PLANE_SECTION_ID:
        return control_plane_payload(current_values=current_values)
    if section_id == CORPUS_FEDERATION_SECTION_ID:
        return corpus_federation_payload(current_values=current_values)
    if section_id == COMMUNITY_STATS_SECTION_ID:
        return community_stats_payload(current_values=current_values)
    if section_id == SERVICE_GATEWAYS_SECTION_ID:
        return service_gateways_payload(current_values=current_values)
    s = get_webui_env_section(section_id)
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
    if section_id == "cmd_perm":
        perm_src = s.model_cls.model_validate(current_values) if current_values is not None else cfg_obj
        base.update(_cmd_perm_payload_extras(perm_src))
    elif section_id == "pallas_webui":
        base.update(_pallas_webui_payload_extras())
    return base


def _pallas_webui_payload_extras() -> dict[str, Any]:
    return {
        "dev_mode_hot_reload": True,
        "field_groups": [
            {
                "id": "security",
                "title": "安全与开发调试",
                "field_names": [
                    "pallas_webui_dev_mode",
                    "pallas_webui_cors",
                    "pallas_webui_allowed_origins",
                ],
                "plugin_config_path": "/plugins/pallas_webui",
            },
            {
                "id": "deploy",
                "title": "网页挂载与前端安装包",
                "field_names": [
                    "pallas_webui_enabled",
                    "pallas_webui_http_base",
                    "pallas_webui_dist_zip_url",
                    "pallas_webui_dist_zip_repo",
                    "pallas_webui_dist_zip_tag",
                    "pallas_webui_dist_zip_asset",
                ],
                "plugin_config_path": "/plugins/pallas_webui",
            },
            {
                "id": "runtime",
                "title": "运行时",
                "field_names": ["pallas_webui_log_lines_max"],
                "plugin_config_path": "/plugins/pallas_webui",
            },
        ],
    }


def _cmd_perm_payload_extras(cfg_obj: Any) -> dict[str, Any]:
    from src.features.cmd_perm.schema import build_command_perm_ui

    overrides = getattr(cfg_obj, "command_permission_overrides", None) or {}
    if not isinstance(overrides, dict):
        overrides = {}
    return {"command_perm_ui": build_command_perm_ui({str(k): str(v) for k, v in overrides.items()})}


def apply_webui_env_section_patch(section_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    from .community_stats_section import COMMUNITY_STATS_SECTION_ID, apply_community_stats_patch
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
    if section_id == COMMUNITY_STATS_SECTION_ID:
        return apply_community_stats_patch(patch)
    if section_id == SERVICE_GATEWAYS_SECTION_ID:
        return apply_service_gateways_patch(patch)
    s = get_webui_env_section(section_id)
    current = s.read_current().model_dump(mode="python")
    allowed = set(s.field_to_env.keys()) - set(s.skip_fields)
    for k in patch:
        if k not in allowed:
            raise ValueError(f"未知配置项: {k}")
    merged = {**current, **patch}
    validated = s.model_cls(**merged).model_dump(mode="python")
    items = {s.field_to_env[k]: env_value_to_str(validated[k]) for k in patch}
    upsert_env_dotenv_items(items)
    if section_id == "message_scrub":
        try:
            from src.features.message_scrub import reload_message_scrub_caches

            reload_message_scrub_caches()
        except Exception:
            pass
    if section_id == "cmd_perm":
        try:
            from src.features.cmd_perm import clear_cmd_perm_cache

            clear_cmd_perm_cache()
        except Exception:
            pass
    elif section_id == "ingress_fanout":
        try:
            from src.platform.ingress.config import clear_ingress_fanout_config_cache

            clear_ingress_fanout_config_cache()
        except Exception:
            pass
    elif section_id == "repeater_learn":
        try:
            import asyncio

            from nonebot import logger

            from src.plugins.repeater.learn_queue import reload_repeater_learn_worker_runtime

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(reload_repeater_learn_worker_runtime())
            except RuntimeError:
                import asyncio as aio

                aio.run(reload_repeater_learn_worker_runtime())
            logger.info("repeater_learn: WebUI 已写入配置，learn 并发/队列已热重载")
        except Exception as e:
            from nonebot import logger

            logger.warning("repeater_learn hot reload failed: {}", e)
    else:
        plugin_module = s.module_label if s.module_label.startswith("src.") else ""
        if plugin_module:
            try:
                from .registry import reload_plugin_config

                reload_plugin_config(plugin_module)
            except Exception:
                pass
    return webui_env_section_payload(section_id, current_values=validated)
