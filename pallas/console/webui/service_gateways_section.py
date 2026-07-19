"""WebUI 外部服务地址与连通检测。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_core import PydanticUndefined

if TYPE_CHECKING:
    from pydantic import BaseModel

from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

from .field_help import normalize_field_description
from .gateway_fields import (
    ALL_GATEWAY_FIELDS,
    MAA_GATEWAY_FIELDS,
    PALLAS_IMAGE_GATEWAY_FIELDS,
    SING_GATEWAY_FIELDS,
)
from .plugin_api import (
    apply_plugin_config_patch,
    field_kind_from_annotation,
    jsonable_value,
)

SERVICE_GATEWAYS_SECTION_ID = "service_gateways"
SERVICE_GATEWAYS_TITLE = "外部服务地址与连通检测"

_PLUGIN_SPECS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("draw", "牛牛画画", PALLAS_IMAGE_GATEWAY_FIELDS),
    ("maa", "MAA 远控", MAA_GATEWAY_FIELDS),
    ("sing", "点歌 / 唱歌", SING_GATEWAY_FIELDS),
)


def _load_config_plugin(plugin_name: str) -> tuple[type[BaseModel], Any]:
    mod = import_plugin_submodule(plugin_name, "config")
    cfg_cls = getattr(mod, "Config", None)
    if cfg_cls is None:
        raise RuntimeError(f"{plugin_name} config 缺少 Config")
    for name in dir(mod):
        if not name.startswith("get_") or not name.endswith("_config"):
            continue
        candidate = getattr(mod, name)
        if callable(candidate):
            return cfg_cls, candidate
    from nonebot import get_plugin_config

    return cfg_cls, lambda: get_plugin_config(cfg_cls)


def _read_gateway_cfg(plugin_name: str) -> Any:
    cfg_cls, getter = _load_config_plugin(plugin_name)
    cfg_obj = getter()
    if plugin_name == "draw":
        from pallas.console.webui.plugin_api import maybe_migrate_draw_config

        cfg_obj = maybe_migrate_draw_config(cfg_obj)
    return cfg_cls, cfg_obj


def _field_row(cfg_cls: type[BaseModel], key: str, cur: Any) -> dict[str, Any]:
    from pallas.console.webui.field_labels import webui_field_label

    f = cfg_cls.model_fields[key]
    default_value = None if f.default is PydanticUndefined else f.default
    row: dict[str, Any] = {
        "name": key,
        "kind": field_kind_from_annotation(f.annotation),
        "required": bool(f.is_required()),
        "description": normalize_field_description(str(f.description or "")),
        "env_key": key.upper(),
        "default": jsonable_value(default_value),
        "current": jsonable_value(cur),
    }
    label = webui_field_label(key)
    if label:
        row["label"] = label
    return row


def service_gateways_payload(
    *,
    current_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    field_groups: list[dict[str, Any]] = []
    for plugin_name, title, keys in _PLUGIN_SPECS:
        cfg_cls, cfg_obj = _read_gateway_cfg(plugin_name)
        group_names: list[str] = []
        ordered_keys = [key for key in cfg_cls.model_fields.keys() if key in keys]
        for key in ordered_keys:
            if current_values is not None:
                cur = current_values.get(key, getattr(cfg_obj, key))
            else:
                cur = getattr(cfg_obj, key)
            fields.append(_field_row(cfg_cls, key, cur))
            group_names.append(key)
        field_groups.append({
            "id": plugin_name,
            "title": title,
            "field_names": group_names,
            "plugin_config_path": f"/plugins/{plugin_name}",
        })
    return {
        "plugin": SERVICE_GATEWAYS_SECTION_ID,
        "module": "pallas.console.webui.service_gateways_section",
        "fields": fields,
        "field_groups": field_groups,
        "gateway_editor": True,
        "supports_connectivity_check": True,
    }


def apply_service_gateways_patch(patch: dict[str, Any]) -> dict[str, Any]:
    unknown = set(patch.keys()) - ALL_GATEWAY_FIELDS
    if unknown:
        raise ValueError(f"未知配置项: {', '.join(sorted(unknown))}")
    merged_all: dict[str, Any] = {}
    for plugin_name, _, keys in _PLUGIN_SPECS:
        sub = {k: v for k, v in patch.items() if k in keys}
        if not sub:
            continue
        data = apply_plugin_config_patch(plugin_name, sub)
        for f in data.get("fields", []):
            merged_all[f["name"]] = f.get("current")
    return service_gateways_payload(current_values=merged_all)
