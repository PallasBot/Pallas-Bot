"""WebUI「按插件名」配置读写。"""

from __future__ import annotations

import importlib
from typing import Any

from nonebot import get_loaded_plugins, get_plugin_config, logger
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from pallas.core.foundation.config.dotenv import env_value_to_str, upsert_env_dotenv_items
from pallas.core.platform.plugin_runtime.plugin_identity import canonical_plugin_id
from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

from .registry import read_plugin_config, reload_plugin_config

_REPEATER_FIELD_TO_ENV = {
    "learn_concurrency": "PALLAS_REPEATER_LEARN_CONCURRENCY",
    "learn_queue_max_size": "PALLAS_REPEATER_LEARN_QUEUE_SIZE",
    "fanout_enabled": "PALLAS_REPEATER_FANOUT_ENABLED",
    "fanout_max_bots": "PALLAS_REPEATER_FANOUT_MAX_BOTS",
}

_PB_STATS_FIELD_TO_ENV = {
    "enabled": "PALLAS_COMMUNITY_STATS_ENABLED",
    "endpoint": "PALLAS_COMMUNITY_STATS_ENDPOINT",
    "token": "PALLAS_COMMUNITY_STATS_TOKEN",
    "interval_sec": "PALLAS_COMMUNITY_STATS_INTERVAL_SEC",
    "roster_public_qq": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_QQ",
    "roster_public_profile": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_PROFILE",
    "corpus_hot_snapshot_interval_sec": "PALLAS_COMMUNITY_STATS_CORPUS_HOT_SNAPSHOT_INTERVAL_SEC",
}


def plugin_field_env_key(plugin_name: str, field_name: str) -> str:
    canonical = canonical_plugin_id((plugin_name or "").strip())
    if canonical == "repeater":
        return _REPEATER_FIELD_TO_ENV.get(field_name, field_name.upper())
    if canonical == "pb_stats":
        return _PB_STATS_FIELD_TO_ENV.get(field_name, field_name.upper())
    return field_name.upper()


def plugin_config_field_groups(plugin_name: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    canonical = canonical_plugin_id((plugin_name or "").strip())
    if canonical != "pb_stats":
        return None
    visible = [f["name"] for f in fields if not f.get("ui_hidden")]
    return [
        {
            "id": "reporting",
            "title": "在线统计",
            "field_names": [name for name in ("enabled", "interval_sec") if name in visible],
        },
        {
            "id": "advanced",
            "title": "自建中心（一般无需改）",
            "field_names": [name for name in ("endpoint", "token") if name in visible],
        },
        {
            "id": "roster",
            "title": "社区主站展示",
            "field_names": [name for name in ("roster_public_qq", "roster_public_profile") if name in visible],
        },
    ]


def schedule_repeater_learn_reload() -> None:
    try:
        import asyncio

        from packages.repeater.learn_queue import reload_repeater_learn_worker_runtime

        loop = asyncio.get_running_loop()
        loop.create_task(reload_repeater_learn_worker_runtime())
    except (RuntimeError, Exception):
        pass


def find_loaded_plugin(plugin_name: str):
    target = canonical_plugin_id((plugin_name or "").strip())
    for p in get_loaded_plugins():
        nb = str(getattr(p, "name", "") or "").strip()
        if canonical_plugin_id(nb) == target:
            return p
        module_name = plugin_module_name(p)
        if module_name and canonical_plugin_id(module_name) == target:
            return p
        short = module_name.rsplit(".", 1)[-1]
        if short and canonical_plugin_id(short) == target:
            return p
    return None


def plugin_module_name(p: Any) -> str:
    mod = getattr(p, "module", None)
    module_name = getattr(mod, "__name__", "") if mod is not None else ""
    if not module_name:
        module_name = str(getattr(p, "module_name", "") or "")
    return module_name.strip()


def maybe_migrate_draw_config(cfg_obj: BaseModel) -> BaseModel:
    draw_config = import_plugin_submodule("draw", "config")
    cfg_cls = getattr(draw_config, "Config", None)
    migrate = getattr(draw_config, "migrate_legacy_gateway_config", None)
    if cfg_cls is None or migrate is None or not isinstance(cfg_obj, cfg_cls):
        return cfg_obj
    return migrate(cfg_obj)


def plugin_config_model_by_name(plugin_name: str):
    canonical = canonical_plugin_id((plugin_name or "").strip())
    if canonical == "pb_core":
        from packages.pb_core.config import Config

        return None, "packages.pb_core", Config
    from pallas.console.webui.plugin_catalog import load_config_class_for_package, resolve_catalog_plugin_module

    p = find_loaded_plugin(plugin_name)
    if p is not None:
        module_name = plugin_module_name(p)
        if not module_name:
            raise ValueError(f"插件模块名为空: {plugin_name}")
        cfg_mod_name = module_name if module_name.endswith(".config") else f"{module_name}.config"
        try:
            cfg_mod = importlib.import_module(cfg_mod_name)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"插件缺少 config.py: {plugin_name}") from e
        cfg_cls = getattr(cfg_mod, "Config", None)
        if cfg_cls is None or not isinstance(cfg_cls, type) or not issubclass(cfg_cls, BaseModel):
            raise ValueError(f"插件 config.py 未定义 Config(BaseModel): {plugin_name}")
        return p, module_name, cfg_cls
    module_name = resolve_catalog_plugin_module(plugin_name)
    if not module_name:
        raise ValueError(f"未找到插件: {plugin_name}")
    cfg_cls = load_config_class_for_package(plugin_name)
    if cfg_cls is None:
        raise ValueError(f"插件缺少 config.py: {plugin_name}")
    return None, module_name, cfg_cls


def field_kind_from_annotation(ann: Any) -> str:
    from .field_meta import field_kind_from_annotation as kind_from_ann

    return kind_from_ann(ann)


def jsonable_value(v: Any) -> Any:
    if v is PydanticUndefined:
        return None
    if isinstance(v, BaseModel):
        return v.model_dump(mode="python")
    if isinstance(v, dict):
        return {str(k): jsonable_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [jsonable_value(x) for x in v]
    if isinstance(v, (set, tuple)):
        return [jsonable_value(x) for x in v]
    return v


def read_current_plugin_config(module_name: str, cfg_cls: type[BaseModel]) -> BaseModel:
    def fallback() -> BaseModel:
        from_env = getattr(cfg_cls, "from_env", None)
        if callable(from_env):
            return from_env()
        try:
            return get_plugin_config(cfg_cls)
        except Exception:
            return cfg_cls()

    return read_plugin_config(module_name, cfg_cls, fallback_getter=fallback)


def format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        msg = str(err.get("msg", "") or "")
        parts.append(f"{loc}: {msg}" if loc else msg)
    text = "; ".join(parts) if parts else str(exc)
    return text[:2000]


def normalize_patch_value(field: Any, value: Any) -> Any:
    """WebUI 空 JSON / null 时对齐 Pydantic 默认值，避免保存 400。"""
    if value is not None:
        return value
    factory = getattr(field, "default_factory", None)
    if factory is not None:
        return factory() if callable(factory) else factory
    if field.default is not PydanticUndefined:
        default = field.default
        if default is not None:
            return default() if callable(default) else default
    ann = str(field.annotation).lower()
    if "list" in ann:
        return []
    if "dict" in ann:
        return {}
    return value


def plugin_config_payload(
    plugin_name: str,
    *,
    current_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """GET 用默认 ``current``；PUT 落盘后应传 ``validated``，避免 ``get_plugin_config`` 仍为旧内存。"""
    if canonical_plugin_id((plugin_name or "").strip()) == "pb_core":
        from packages.pb_core.config import pb_core_webui_payload

        return pb_core_webui_payload(current_values=current_values)
    p, module_name, cfg_cls = plugin_config_model_by_name(plugin_name)
    cfg_obj = read_current_plugin_config(module_name, cfg_cls)
    if plugin_name == "draw":
        cfg_obj = maybe_migrate_draw_config(cfg_obj)
    fields: list[dict[str, Any]] = []
    for key, f in cfg_cls.model_fields.items():
        if current_values is not None:
            cur = current_values.get(key, getattr(cfg_obj, key, f.default))
        else:
            cur = getattr(cfg_obj, key, f.default)
        default_value = None if f.default is PydanticUndefined else f.default
        from .field_meta import field_meta_for_model_field

        row = field_meta_for_model_field(
            key=key,
            field=f,
            env_key=plugin_field_env_key(plugin_name, key),
            cur=cur,
            default_value=default_value,
        )
        extra = getattr(f, "json_schema_extra", None)
        if isinstance(extra, dict) and extra.get("ui_hidden"):
            row["ui_hidden"] = True
        fields.append(row)
    payload: dict[str, Any] = {
        "plugin": str(getattr(p, "name", "") or plugin_name) if p is not None else plugin_name,
        "module": module_name,
        "fields": fields,
        "unexpected_keys": plugin_unexpected_env_keys(plugin_name, cfg_cls),
        "hot_reload": True,
    }
    groups = plugin_config_field_groups(plugin_name, fields)
    if groups:
        payload["field_groups"] = groups
    return payload


def plugin_config_env_keys(plugin_name: str, cfg_cls: type[BaseModel]) -> set[str]:
    return {plugin_field_env_key(plugin_name, key) for key in cfg_cls.model_fields}


def plugin_unexpected_env_keys(plugin_name: str, cfg_cls: type[BaseModel]) -> list[dict[str, str]]:
    from pallas.core.foundation.config.repo_settings import _load_webui_json_upper

    allowed = plugin_config_env_keys(plugin_name, cfg_cls)
    prefix = f"{plugin_name.upper().replace('-', '_')}_"
    env = _load_webui_json_upper()
    rows: list[dict[str, str]] = []
    for key, value in sorted(env.items()):
        upper = str(key).upper()
        if upper in allowed:
            continue
        if not (upper.startswith(prefix) or upper in allowed):
            continue
        preview = str(value)
        if len(preview) > 120:
            preview = preview[:119] + "…"
        rows.append({"env_key": upper, "value_preview": preview})
    return rows


def plugin_config_raw_toml(plugin_name: str) -> str:
    import json

    _, _, cfg_cls = plugin_config_model_by_name(plugin_name)
    from pallas.core.foundation.config.repo_settings import _load_webui_json_upper

    env = _load_webui_json_upper()
    lines = [f"# plugin: {plugin_name}", "", "[env]"]
    for field_key in cfg_cls.model_fields:
        env_key = plugin_field_env_key(plugin_name, field_key)
        if env_key in env:
            lines.append(f"{env_key} = {json.dumps(str(env[env_key]), ensure_ascii=False)}")
    for row in plugin_unexpected_env_keys(plugin_name, cfg_cls):
        ek = row["env_key"]
        if ek in env:
            lines.append(f"{ek} = {json.dumps(str(env[ek]), ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines)


def apply_plugin_config_raw_toml(plugin_name: str, text: str) -> dict[str, Any]:
    import tomllib

    raw = (text or "").strip()
    if not raw:
        raise ValueError("TOML 内容为空")
    try:
        doc = tomllib.loads(raw.encode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"TOML 解析失败: {exc}") from exc
    env_block = doc.get("env") if isinstance(doc.get("env"), dict) else doc
    if not isinstance(env_block, dict):
        raise ValueError("缺少 [env] 表")
    _, _, cfg_cls = plugin_config_model_by_name(plugin_name)
    reverse = {plugin_field_env_key(plugin_name, key): key for key in cfg_cls.model_fields}
    patch: dict[str, Any] = {}
    for env_key, value in env_block.items():
        field_key = reverse.get(str(env_key).upper())
        if field_key:
            patch[field_key] = value
    if not patch:
        raise ValueError("没有可识别的插件配置键")
    return apply_plugin_config_patch(plugin_name, patch)


def apply_plugin_config_patch(
    plugin_name: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    if canonical_plugin_id((plugin_name or "").strip()) == "pb_core":
        from packages.pb_core.config import apply_pb_core_patch

        return apply_pb_core_patch(patch)
    _, module_name, cfg_cls = plugin_config_model_by_name(plugin_name)
    current = read_current_plugin_config(module_name, cfg_cls).model_dump(mode="python")
    allowed = set(cfg_cls.model_fields.keys())
    normalized: dict[str, Any] = {}
    for k, v in patch.items():
        if k not in allowed:
            raise ValueError(
                f"未知配置项: {k}（请确认 Bot 已更新并重启；WebUI 无需单独加字段表）",
            )
        normalized[k] = normalize_patch_value(cfg_cls.model_fields[k], v)
    merged = {**current, **normalized}
    try:
        validated_obj = cfg_cls(**merged)
        if plugin_name == "draw":
            validated_obj = maybe_migrate_draw_config(validated_obj)
        validated = validated_obj.model_dump(mode="python")
    except ValidationError as e:
        raise ValueError(format_validation_error(e)) from e
    env_items = {plugin_field_env_key(plugin_name, k): env_value_to_str(validated[k]) for k in normalized}
    upsert_env_dotenv_items(env_items)
    try:
        reload_plugin_config(module_name)
    except Exception:
        pass
    try:
        from pallas.core.plugin_reload.metadata_index import reload_metadata_after_plugin_config_save

        reload_metadata_after_plugin_config_save(plugin_name)
    except Exception:
        logger.exception("plugin config save: metadata index reload failed plugin={}", plugin_name)
    canonical = canonical_plugin_id((plugin_name or "").strip())
    if canonical == "repeater" and {"learn_concurrency", "learn_queue_max_size"} & normalized.keys():
        schedule_repeater_learn_reload()
    return plugin_config_payload(plugin_name, current_values=validated)
