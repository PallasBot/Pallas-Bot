"""WebUI「按插件名」配置读写（供 ``pallas_webui.extended_api`` 调用）。"""

from __future__ import annotations

import importlib
from typing import Any

from nonebot import get_loaded_plugins, get_plugin_config
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticUndefined

from src.common.config.dotenv import env_value_to_str, upsert_env_dotenv_items

from .registry import read_plugin_config, reload_plugin_config

_REPEATER_FIELD_TO_ENV = {
    "learn_concurrency": "PALLAS_REPEATER_LEARN_CONCURRENCY",
    "learn_queue_max_size": "PALLAS_REPEATER_LEARN_QUEUE_SIZE",
}


def plugin_field_env_key(plugin_name: str, field_name: str) -> str:
    if plugin_name == "repeater":
        return _REPEATER_FIELD_TO_ENV.get(field_name, field_name.upper())
    return field_name.upper()


def schedule_repeater_learn_reload() -> None:
    try:
        import asyncio

        from src.plugins.repeater.learn_queue import reload_repeater_learn_worker_runtime

        loop = asyncio.get_running_loop()
        loop.create_task(reload_repeater_learn_worker_runtime())
    except (RuntimeError, Exception):
        pass


def find_loaded_plugin(plugin_name: str):
    target = (plugin_name or "").strip()
    for p in get_loaded_plugins():
        nb = str(getattr(p, "name", "") or "").strip()
        if nb == target:
            return p
        short = plugin_module_name(p).rsplit(".", 1)[-1]
        if short and short == target:
            return p
    return None


def plugin_module_name(p: Any) -> str:
    mod = getattr(p, "module", None)
    module_name = getattr(mod, "__name__", "") if mod is not None else ""
    if not module_name:
        module_name = str(getattr(p, "module_name", "") or "")
    return module_name.strip()


def plugin_config_model_by_name(plugin_name: str):
    from src.common.webui.plugin_catalog import load_config_class_for_package, resolve_catalog_plugin_module

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
    p, module_name, cfg_cls = plugin_config_model_by_name(plugin_name)
    cfg_obj = read_current_plugin_config(module_name, cfg_cls)
    if plugin_name == "pallas_image":
        from src.plugins.pallas_image.config import Config as PallasImageConfig
        from src.plugins.pallas_image.config import migrate_legacy_gateway_config

        if isinstance(cfg_obj, PallasImageConfig):
            cfg_obj = migrate_legacy_gateway_config(cfg_obj)
    fields: list[dict[str, Any]] = []
    for key, f in cfg_cls.model_fields.items():
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
                env_key=plugin_field_env_key(plugin_name, key),
                cur=cur,
                default_value=default_value,
            )
        )
    return {
        "plugin": str(getattr(p, "name", "") or plugin_name) if p is not None else plugin_name,
        "module": module_name,
        "fields": fields,
    }


def apply_plugin_config_patch(
    plugin_name: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
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
        if plugin_name == "pallas_image":
            from src.plugins.pallas_image.config import migrate_legacy_gateway_config

            validated_obj = migrate_legacy_gateway_config(validated_obj)
        validated = validated_obj.model_dump(mode="python")
    except ValidationError as e:
        raise ValueError(format_validation_error(e)) from e
    env_items = {plugin_field_env_key(plugin_name, k): env_value_to_str(validated[k]) for k in normalized}
    upsert_env_dotenv_items(env_items)
    try:
        reload_plugin_config(module_name)
    except Exception:
        pass
    if plugin_name == "repeater" and {"learn_concurrency", "learn_queue_max_size"} & normalized.keys():
        schedule_repeater_learn_reload()
    return plugin_config_payload(plugin_name, current_values=validated)
