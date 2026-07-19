"""连通探测用 WebUI 草稿合并。"""

from __future__ import annotations

from typing import Any

from pallas.console.webui.gateway_fields import MAA_GATEWAY_FIELDS, PALLAS_IMAGE_GATEWAY_FIELDS, SING_GATEWAY_FIELDS


def draft_subset(values: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k in keys}


def draw_draft_from_values(values: dict[str, Any]) -> dict[str, Any]:
    from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

    draw_config = import_plugin_submodule("draw", "config")
    base = draw_config.get_draw_config().model_dump(mode="python")
    base.update(draft_subset(values, PALLAS_IMAGE_GATEWAY_FIELDS))
    return base


def maa_cfg_from_draft(values: dict[str, Any]):
    from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

    maa_config = import_plugin_submodule("maa", "config")
    maa_config_model = maa_config.Config
    get_maa_config = maa_config.get_maa_config
    base = get_maa_config().model_dump(mode="python")
    base.update(draft_subset(values, MAA_GATEWAY_FIELDS))
    return maa_config_model.model_validate(base)


def sing_cfg_from_draft(values: dict[str, Any]):
    from pallas.core.platform.plugin_runtime.resolve import import_plugin_submodule

    sing_config = import_plugin_submodule("sing", "config")
    sing_config_model = sing_config.Config
    get_sing_config = sing_config.get_sing_config
    base = get_sing_config().model_dump(mode="python")
    base.update(draft_subset(values, SING_GATEWAY_FIELDS))
    return sing_config_model.model_validate(base)
