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
    roster_public_qq: bool = Field(
        default=False,
        description="是否在社区主站公开牛牛 QQ 号（可点开 QQ 资料）。",
    )
    roster_public_profile: bool = Field(
        default=False,
        description="是否在社区主站公开牛牛昵称与头像。",
    )

    @property
    def roster_public(self) -> bool:
        return self.roster_public_qq or self.roster_public_profile


def _read_roster_public_flags() -> tuple[bool, bool]:
    legacy_raw = repo_env_raw_value(f"{_PREFIX}ROSTER_PUBLIC")
    qq_raw = repo_env_raw_value(f"{_PREFIX}ROSTER_PUBLIC_QQ")
    profile_raw = repo_env_raw_value(f"{_PREFIX}ROSTER_PUBLIC_PROFILE")
    if qq_raw is None and profile_raw is None and legacy_raw is not None:
        legacy = _setting_bool(f"{_PREFIX}ROSTER_PUBLIC", False)
        return legacy, legacy
    return (
        _setting_bool(f"{_PREFIX}ROSTER_PUBLIC_QQ", False),
        _setting_bool(f"{_PREFIX}ROSTER_PUBLIC_PROFILE", False),
    )


@lru_cache(maxsize=1)
def get_community_stats_config() -> CommunityStatsConfig:
    roster_qq, roster_profile = _read_roster_public_flags()
    return CommunityStatsConfig(
        enabled=_setting_bool(f"{_PREFIX}ENABLED", True),
        endpoint=_setting_str(f"{_PREFIX}ENDPOINT", "https://stats.pallasbot.top/v1/heartbeat"),
        token=_setting_str(f"{_PREFIX}TOKEN", ""),
        interval_sec=_setting_int(f"{_PREFIX}INTERVAL_SEC", 300),
        roster_public_qq=roster_qq,
        roster_public_profile=roster_profile,
    )


def clear_community_stats_config_cache() -> None:
    get_community_stats_config.cache_clear()
