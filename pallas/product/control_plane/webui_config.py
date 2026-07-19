"""WebUI 控制面与入站协同配置。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui.field_help import field_help
from pallas.core.foundation.config.repo_settings import repo_env_raw_value, repo_webui_settings_path
from pallas.product.corpus.config import parse_tristate

_FEDERATE_COORD_URL_KEY = "PALLAS_FEDERATE_COORD_REDIS_URL"
_LEGACY_COORD_URL_KEY = "PALLAS_COORD_REDIS_URL"


def setting_str(name: str, default: str = "") -> str:
    raw = repo_env_raw_value(name)
    if raw is None:
        return default
    return (raw or "").strip() or default


class ControlPlaneWebuiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        description=field_help(
            "是否自动从社区中心拉取多机协同配置",
            "开启后填写下方中心地址与密钥即可；关闭则完全本地运行",
        ),
    )
    bootstrap_url: str = Field(
        default="",
        description=field_help(
            "多机协同中心的网址",
            "留空时程序自动选择官方主站或备站",
        ),
    )
    instance_secret: str = Field(
        default="",
        description=field_help(
            "加入协同时用的密钥",
            "与中心分配的一致；多套牛牛共池时必填",
        ),
    )
    federate_id: str = Field(
        default="",
        description=field_help(
            "本站在社区中的编号",
            "可留空，由中心在首次登记时写入",
        ),
    )
    federate_ingress_enabled: str = Field(
        default="auto",
        description=field_help(
            "多机部署时是否过滤重复群消息",
            "选自动、开启或关闭；单进程一般保持自动",
        ),
    )
    ingress_bypass_unified: bool = Field(
        default=False,
        description=field_help(
            "单进程运行时是否跳过重复消息过滤",
            "仅一只牛、一个进程时可开启；多 worker 勿开",
        ),
    )
    federate_redis_prefix: str = Field(
        default="",
        description=field_help(
            "去重记录在 Redis 中的键前缀",
            "一般留空即可",
        ),
    )
    coord_redis_url: str = Field(
        default="",
        description=field_help(
            "多进程共用的去重服务地址",
            "留空时由中心下发；与分片用的 Redis 不是同一项",
        ),
    )
    claim_ttl_sec: int = Field(
        default=86400,
        description=field_help(
            "一条群消息被某只牛认领后，记录保留多久（秒）",
            "默认 86400（一天）；过期后其他牛可再次响应",
        ),
    )


def repair_misplaced_federate_redis_env() -> bool:
    """修正误将分片 REDIS_URL 写入 PALLAS_COORD_REDIS_URL 的情况。"""
    import json

    path = repo_webui_settings_path()
    if not path.is_file():
        return False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(doc, dict):
        return False
    env = doc.get("env")
    if not isinstance(env, dict):
        return False
    redis_url = str(env.get("REDIS_URL") or "").strip()
    coord_url = str(env.get(_LEGACY_COORD_URL_KEY) or "").strip()
    fed_url = str(env.get(_FEDERATE_COORD_URL_KEY) or "").strip()
    changed = False
    if fed_url and coord_url == fed_url and coord_url != redis_url:
        env.pop(_LEGACY_COORD_URL_KEY, None)
        changed = True
    if not fed_url and coord_url and redis_url and coord_url == redis_url:
        env.pop(_LEGACY_COORD_URL_KEY, None)
        changed = True
    if not changed:
        return False
    from pallas.core.foundation.config.repo_settings import remove_repo_settings_keys

    remove_repo_settings_keys([_LEGACY_COORD_URL_KEY])
    return True


def resolved_coord_redis_url_for_webui() -> str:
    """WebUI 展示：仅显式联邦 URL 或 bootstrap 落盘，不含分片 REDIS_URL。"""
    repair_misplaced_federate_redis_env()
    explicit = setting_str(_FEDERATE_COORD_URL_KEY)
    if explicit:
        return explicit
    try:
        from pallas.product.control_plane.store import load_bootstrap_coord_redis_url

        return load_bootstrap_coord_redis_url()
    except Exception:
        return ""


def resolved_claim_ttl_sec_for_webui() -> int:
    raw = setting_str("PALLAS_FEDERATE_CLAIM_TTL_SEC")
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    try:
        from pallas.product.control_plane.store import load_bootstrap_claim_ttl_sec

        boot = load_bootstrap_claim_ttl_sec()
        if boot is not None:
            return boot
    except Exception:
        pass
    return 86400


@lru_cache(maxsize=1)
def get_control_plane_webui_config() -> ControlPlaneWebuiConfig:
    repair_misplaced_federate_redis_env()
    enabled_raw = setting_str("PALLAS_CONTROL_PLANE_ENABLED", "true")
    enabled_flag = parse_tristate(enabled_raw, default=True)
    fid = setting_str("PALLAS_FEDERATE_ID")
    if not fid:
        try:
            from pallas.product.community_stats.store import load_community_stats_state

            fid = str(load_community_stats_state().get("federate_id") or "").strip()
        except Exception:
            fid = ""
    return ControlPlaneWebuiConfig(
        enabled=enabled_flag is not False,
        bootstrap_url=setting_str("PALLAS_CONTROL_PLANE_BOOTSTRAP_URL"),
        instance_secret=setting_str("PALLAS_INSTANCE_SECRET"),
        federate_id=fid,
        federate_ingress_enabled=setting_str("PALLAS_FEDERATE_INGRESS_ENABLED", "auto") or "auto",
        ingress_bypass_unified=parse_tristate(
            setting_str("PALLAS_FEDERATE_INGRESS_BYPASS_UNIFIED", "false"),
            default=False,
        )
        is True,
        federate_redis_prefix=setting_str("PALLAS_FEDERATE_REDIS_PREFIX"),
        coord_redis_url=resolved_coord_redis_url_for_webui(),
        claim_ttl_sec=resolved_claim_ttl_sec_for_webui(),
    )


def clear_control_plane_webui_config_cache() -> None:
    get_control_plane_webui_config.cache_clear()
