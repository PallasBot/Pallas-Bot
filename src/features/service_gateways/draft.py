"""WebUI 草稿配置合并（连通性探测用）。"""

from __future__ import annotations

from typing import Any

from src.console.webui.gateway_fields import MAA_GATEWAY_FIELDS, PALLAS_IMAGE_GATEWAY_FIELDS, SING_GATEWAY_FIELDS


def draft_subset(values: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k in keys}


def draw_draft_from_values(values: dict[str, Any]) -> dict[str, Any]:
    from src.plugins.draw.config import get_draw_config

    base = get_draw_config().model_dump(mode="python")
    base.update(draft_subset(values, PALLAS_IMAGE_GATEWAY_FIELDS))
    return base


def maa_cfg_from_draft(values: dict[str, Any]):
    from src.plugins.maa.config import Config as MaaConfig
    from src.plugins.maa.config import get_maa_config

    base = get_maa_config().model_dump(mode="python")
    base.update(draft_subset(values, MAA_GATEWAY_FIELDS))
    return MaaConfig.model_validate(base)


def sing_cfg_from_draft(values: dict[str, Any]):
    from src.plugins.sing.config import Config as SingConfig
    from src.plugins.sing.config import get_sing_config

    base = get_sing_config().model_dump(mode="python")
    base.update(draft_subset(values, SING_GATEWAY_FIELDS))
    return SingConfig.model_validate(base)
