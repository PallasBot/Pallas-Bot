"""社区统计 opt-in 上报配置（pallas.toml [community_stats] 或环境变量）。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from src.foundation.config.repo_settings import repo_env_raw_value

_PREFIX = "PALLAS_COMMUNITY_STATS_"


def _setting_str(name: str, default: str = "") -> str:
    raw = repo_env_raw_value(name)
    if raw is None:
        return default
    return (raw or "").strip() or default


def _setting_int(name: str, default: int) -> int:
    raw = _setting_str(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _setting_bool(name: str, default: bool) -> bool:
    raw = _setting_str(name, "")
    if not raw:
        return default
    return raw.lower() not in ("0", "false", "no", "off")


class CommunityStatsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="是否向社区统计中心上报心跳。")
    endpoint: str = Field(
        default="https://stats.pallasbot.top/v1/heartbeat",
        description="心跳 URL（POST）。",
    )
    token: str = Field(
        default="",
        description="可选 Bearer；中心 HEARTBEAT_TOKEN 非空时填写。公开实例（token 未配置）可留空。",
    )
    interval_sec: int = Field(default=300, ge=60, le=3600, description="周期上报间隔（秒）。")
    roster_public: bool = Field(
        default=False,
        description="是否向社区主站公开本部署牛牛名册（昵称、在线态、近 7 日消息量权重）。",
    )


@lru_cache(maxsize=1)
def get_community_stats_config() -> CommunityStatsConfig:
    return CommunityStatsConfig(
        enabled=_setting_bool(f"{_PREFIX}ENABLED", True),
        endpoint=_setting_str(f"{_PREFIX}ENDPOINT", "https://stats.pallasbot.top/v1/heartbeat"),
        token=_setting_str(f"{_PREFIX}TOKEN", ""),
        interval_sec=_setting_int(f"{_PREFIX}INTERVAL_SEC", 300),
        roster_public=_setting_bool(f"{_PREFIX}ROSTER_PUBLIC", False),
    )


def clear_community_stats_config_cache() -> None:
    get_community_stats_config.cache_clear()
