"""方舟知识库开关。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui.field_help import field_help
from pallas.core.foundation.config.repo_settings import repo_env_raw_value


def env_bool(key: str, default: bool) -> bool:
    raw = repo_env_raw_value(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class ArknightsKbConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    arknights_kb_enabled: bool = Field(
        default=True,
        description=field_help("是否启用方舟干员结构化查询", "关闭后 LLM tools 与查询 API 均不可用"),
    )
    arknights_kb_auto_sync: bool = Field(
        default=True,
        description=field_help("缺干员数据时后台自动同步", "与决斗插件共用 resource/arknights/"),
    )


def get_arknights_kb_config() -> ArknightsKbConfig:
    return ArknightsKbConfig(
        arknights_kb_enabled=env_bool("ARKNIGHTS_KB_ENABLED", True),
        arknights_kb_auto_sync=env_bool("ARKNIGHTS_KB_AUTO_SYNC", True),
    )
