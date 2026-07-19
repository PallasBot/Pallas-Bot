"""供插件 ``config.py`` 使用：磁盘配置热重载 + 自动注册 WebUI 钩子。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any, TypeVar

from nonebot import get_plugin_config
from pydantic import BaseModel

from pallas.core.foundation.config.dotenv import repo_env_raw_value, repo_settings_files_exist
from pallas.core.foundation.config.repo_settings import repo_settings_disk_revision

from .registry import PluginWebuiConfigHooks, register_plugin_webui_config

C = TypeVar("C", bound=BaseModel)
ParseEnvValue = Callable[[str, str, Any], Any]
OnReload = Callable[[Any], None]


def default_parse_env_value(name: str, raw: str, ann: Any) -> Any:  # noqa: ARG001
    text = raw.strip()
    ann_text = str(ann).lower()
    if "bool" in ann_text:
        return text.lower() in ("1", "true", "yes", "on")
    if "list" in ann_text or "dict" in ann_text or "set" in ann_text:
        if not text:
            return [] if "list" in ann_text else {}
        return json.loads(text)
    if "float" in ann_text and "list" not in ann_text:
        return float(text)
    if "int" in ann_text and "list" not in ann_text:
        return int(text)
    return text


def env_key_for_field(name: str, field_to_env: dict[str, str] | None) -> str:
    if field_to_env and name in field_to_env:
        return field_to_env[name]
    return name.upper()


def config_from_env[C: BaseModel](
    config_cls: type[C],
    *,
    parse_env_value: ParseEnvValue | None = None,
    field_to_env: dict[str, str] | None = None,
) -> C:
    parse = parse_env_value or default_parse_env_value
    data: dict[str, Any] = {}
    for name, field in config_cls.model_fields.items():
        key = env_key_for_field(name, field_to_env)
        raw = repo_env_raw_value(key)
        if raw is None:
            continue
        data[name] = parse(name, str(raw), field.annotation)
    return config_cls.model_validate(data)


class PluginConfigProxy[C: BaseModel]:
    """兼容 ``plugin_config.xxx``；每次属性访问读取当前缓存配置。"""

    def __init__(self, getter: Callable[[], C]) -> None:
        self._getter = getter

    def __getattr__(self, name: str) -> Any:
        return getattr(self._getter(), name)


def plugin_config_proxy[C: BaseModel](getter: Callable[[], C]) -> PluginConfigProxy[C]:
    return PluginConfigProxy(getter)


@dataclass(frozen=True)
class PluginWebuiConfigHandle:
    get: Callable[[], Any]
    reload: Callable[[], None]
    clear_cache: Callable[[], None]


def install_hot_reload_config[C: BaseModel](
    config_cls: type[C],
    *,
    config_module: str,
    parse_env_value: ParseEnvValue | None = None,
    field_to_env: dict[str, str] | None = None,
    on_reload: OnReload | None = None,
    register_keys: tuple[str, ...] | None = None,
) -> PluginWebuiConfigHandle:
    """创建带缓存的 get/reload，并登记到 ``registry``。"""
    lock = Lock()
    cached: C | None = None
    disk_rev: tuple[tuple[int, int], ...] | None = None
    parse = parse_env_value or default_parse_env_value

    def clear_cache() -> None:
        nonlocal cached, disk_rev
        with lock:
            cached = None
            disk_rev = None

    def get() -> C:
        nonlocal cached, disk_rev
        rev = repo_settings_disk_revision()
        with lock:
            if disk_rev is not None and rev != disk_rev:
                cached = None
                from pallas.core.foundation.config.repo_settings import clear_merged_repo_settings_cache

                clear_merged_repo_settings_cache()
            disk_rev = rev
            if cached is None:
                if repo_settings_files_exist():
                    cached = config_from_env(
                        config_cls,
                        parse_env_value=parse,
                        field_to_env=field_to_env,
                    )
                else:
                    cached = get_plugin_config(config_cls)
            return cached

    def reload() -> None:
        clear_cache()
        cfg = get()
        if on_reload is not None:
            on_reload(cfg)

    handle = PluginWebuiConfigHandle(get=get, reload=reload, clear_cache=clear_cache)
    hooks = PluginWebuiConfigHooks(get=get, reload=reload, clear_cache=clear_cache)
    keys = register_keys if register_keys is not None else (config_module,)
    for key in keys:
        register_plugin_webui_config(key, hooks)
    return handle
