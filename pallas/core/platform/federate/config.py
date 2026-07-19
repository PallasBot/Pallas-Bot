"""多机协同入站与 Redis 配置。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.platform.federate.redis_settings import federate_redis_available
from pallas.core.platform.shard import context as shard_ctx

_PREFIX = "PALLAS_FEDERATE_"


def setting_str(name: str, default: str = "") -> str:
    raw = repo_env_raw_value(name)
    if raw is None:
        return default
    return (raw or "").strip() or default


def parse_tristate(raw: str, *, default: bool | None = None) -> bool | None:
    s = (raw or "").strip().lower()
    if s in ("auto", ""):
        return default
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


class FederateConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    control_plane_enabled: bool | None = Field(default=None)
    federate_id: str = Field(default="")
    ingress_enabled: bool | None = Field(default=None)
    ingress_bypass_unified: bool | None = Field(default=None)
    redis_prefix: str = Field(default="")


@lru_cache(maxsize=1)
def get_federate_config() -> FederateConfig:
    cp_flag = parse_tristate(setting_str("PALLAS_CONTROL_PLANE_ENABLED", "true"), default=True)
    ingress_flag = parse_tristate(setting_str(f"{_PREFIX}INGRESS_ENABLED", "auto"), default=None)
    return FederateConfig(
        control_plane_enabled=cp_flag,
        federate_id=setting_str(f"{_PREFIX}ID"),
        ingress_enabled=ingress_flag,
        ingress_bypass_unified=parse_tristate(
            setting_str(f"{_PREFIX}INGRESS_BYPASS_UNIFIED", "false"),
            default=False,
        ),
        redis_prefix=setting_str(f"{_PREFIX}REDIS_PREFIX"),
    )


def clear_federate_config_cache() -> None:
    from pallas.core.platform.federate.redis_settings import clear_federate_redis_client_cache

    get_federate_config.cache_clear()
    clear_federate_redis_client_cache()


def load_persisted_federate_id() -> str:
    from pallas.product.community_stats.store import load_community_stats_state

    return str(load_community_stats_state().get("federate_id") or "").strip()


def resolved_federate_id(cfg: FederateConfig | None = None) -> str:
    cfg = cfg or get_federate_config()
    for candidate in (cfg.federate_id, load_persisted_federate_id()):
        fid = (candidate or "").strip()
        if fid:
            return fid
    return ""


def federate_redis_prefix(cfg: FederateConfig | None = None) -> str:
    cfg = cfg or get_federate_config()
    try:
        from pallas.product.control_plane.store import load_bootstrap_coord_redis_prefix

        boot_prefix = load_bootstrap_coord_redis_prefix().rstrip(":")
        if boot_prefix:
            return boot_prefix
    except Exception:
        pass
    explicit = (cfg.redis_prefix or "").strip().rstrip(":")
    if explicit:
        return explicit
    fid = resolved_federate_id(cfg)
    if not fid:
        return ""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in fid)
    return f"pallas:fed:{safe}"


def federate_ingress_enabled(cfg: FederateConfig | None = None) -> bool:
    cfg = cfg or get_federate_config()
    if not shard_ctx.sharding_active() and cfg.ingress_enabled is not True:
        return False
    if cfg.control_plane_enabled is False and cfg.ingress_enabled is not True:
        return False
    flag = cfg.ingress_enabled
    if flag is True:
        return True
    if flag is False:
        return False
    return bool(resolved_federate_id(cfg))


def federate_ingress_bypass_unified(cfg: FederateConfig | None = None) -> bool:
    cfg = cfg or get_federate_config()
    return bool(cfg.ingress_bypass_unified)


def federate_ingress_active() -> bool:
    if not federate_ingress_enabled():
        return False
    if not resolved_federate_id():
        return False
    return federate_redis_available()
