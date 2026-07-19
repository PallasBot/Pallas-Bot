"""控制面 bootstrap 配置。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.product.corpus.config import parse_tristate

_PREFIX = "PALLAS_CONTROL_PLANE_"
_INSTANCE_SECRET_KEY = "PALLAS_INSTANCE_SECRET"


def setting_str(name: str, default: str = "") -> str:
    raw = repo_env_raw_value(name)
    if raw is None:
        return default
    return (raw or "").strip() or default


class ControlPlaneConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool | None = Field(default=None)
    bootstrap_url: str = Field(default="")
    instance_secret: str = Field(default="")


@lru_cache(maxsize=1)
def get_control_plane_config() -> ControlPlaneConfig:
    enabled_flag = parse_tristate(setting_str(f"{_PREFIX}ENABLED", "true"), default=True)
    return ControlPlaneConfig(
        enabled=enabled_flag,
        bootstrap_url=setting_str(f"{_PREFIX}BOOTSTRAP_URL"),
        instance_secret=setting_str(_INSTANCE_SECRET_KEY),
    )


def clear_control_plane_config_cache() -> None:
    get_control_plane_config.cache_clear()


def control_plane_wanted(cfg: ControlPlaneConfig | None = None) -> bool:
    cfg = cfg or get_control_plane_config()
    if cfg.enabled is True:
        return True
    if cfg.enabled is False:
        return False
    return bool(cfg.bootstrap_url.strip() or cfg.instance_secret.strip())


def should_run_bootstrap_refresh() -> bool:
    from pallas.core.platform.bot_runtime.roles import is_sharded_worker

    if is_sharded_worker():
        return False
    cfg = get_control_plane_config()
    if not control_plane_wanted(cfg):
        return False
    if not (cfg.instance_secret or "").strip():
        return False
    from pallas.product.control_plane.bootstrap_client import bootstrap_urls

    return bool(bootstrap_urls(cfg))
