"""MAA 扩展与分片协调的桥接。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.features.plugin_coord._lazy import import_symbol_any

if TYPE_CHECKING:
    from collections.abc import Callable

_normalize_device_id: Callable[[str], str | None] | None = None
_get_maa_config: Callable[[], Any] | None = None
_normalize_http_path: Callable[[str], str] | None = None

_DEFAULT_SEEN_TTL = 300


def register_maa_coord(
    *,
    normalize_device_id: Callable[[str], str | None] | None = None,
    get_maa_config: Callable[[], Any] | None = None,
    normalize_http_path: Callable[[str], str] | None = None,
) -> None:
    g = globals()
    if normalize_device_id is not None:
        g["_normalize_device_id"] = normalize_device_id
    if get_maa_config is not None:
        g["_get_maa_config"] = get_maa_config
    if normalize_http_path is not None:
        g["_normalize_http_path"] = normalize_http_path


_MAA_TASKS = ("pallas_plugin_maa.tasks", "src.plugins.maa.tasks")
_MAA_CONFIG = ("pallas_plugin_maa.config", "src.plugins.maa.config")
_MAA_ENDPOINTS = ("pallas_plugin_maa.endpoints", "src.plugins.maa.endpoints")


def normalize_device_id(raw: str) -> str | None:
    if _normalize_device_id is not None:
        return _normalize_device_id(raw)
    fn = import_symbol_any(_MAA_TASKS, "normalize_device_id")
    if fn is None:
        return None
    return fn(raw)


def get_maa_config() -> Any:
    if _get_maa_config is not None:
        return _get_maa_config()
    fn = import_symbol_any(_MAA_CONFIG, "get_maa_config")
    if fn is None:
        return type("MaaConfigStub", (), {"maa_seen_ttl_seconds": _DEFAULT_SEEN_TTL})()
    return fn()


def normalize_http_path(path: str) -> str:
    if _normalize_http_path is not None:
        return _normalize_http_path(path)
    fn = import_symbol_any(_MAA_ENDPOINTS, "normalize_http_path")
    if fn is None:
        p = (path or "").strip() or "/"
        return p if p.startswith("/") else f"/{p}"
    return fn(path)
