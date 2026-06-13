"""WebUI「通用配置 → 在线统计与社区主站」。"""

from __future__ import annotations

from typing import Any

from pydantic_core import PydanticUndefined

from src.console.webui.field_help import field_help, normalize_field_description
from src.features.community_stats.config import CommunityStatsConfig, get_community_stats_config
from src.foundation.config.dotenv import env_value_to_str
from src.foundation.config.repo_settings import upsert_repo_settings_items

COMMUNITY_STATS_SECTION_ID = "community_stats"
COMMUNITY_STATS_TITLE = "在线统计与社区主站"

_FIELD_NAMES: tuple[str, ...] = (
    "community_stats_enabled",
    "community_stats_endpoint",
    "community_stats_token",
    "community_stats_interval_sec",
    "community_stats_roster_public_qq",
    "community_stats_roster_public_profile",
)

_FIELD_TO_ENV: dict[str, str] = {
    "community_stats_enabled": "PALLAS_COMMUNITY_STATS_ENABLED",
    "community_stats_endpoint": "PALLAS_COMMUNITY_STATS_ENDPOINT",
    "community_stats_token": "PALLAS_COMMUNITY_STATS_TOKEN",
    "community_stats_interval_sec": "PALLAS_COMMUNITY_STATS_INTERVAL_SEC",
    "community_stats_roster_public_qq": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_QQ",
    "community_stats_roster_public_profile": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_PROFILE",
}

_INTERVAL_CHOICES = ["60", "120", "300", "600", "900", "1800", "3600"]

_FIELD_LABELS: dict[str, str] = {
    "community_stats_enabled": "上报在线统计",
    "community_stats_endpoint": "统计上报地址",
    "community_stats_token": "统计上报口令",
    "community_stats_interval_sec": "上报间隔",
    "community_stats_roster_public_qq": "公开牛牛 QQ",
    "community_stats_roster_public_profile": "公开牛牛头像昵称",
}

_WEBUI_TO_MODEL: dict[str, str] = {
    "community_stats_enabled": "enabled",
    "community_stats_endpoint": "endpoint",
    "community_stats_token": "token",
    "community_stats_interval_sec": "interval_sec",
    "community_stats_roster_public_qq": "roster_public_qq",
    "community_stats_roster_public_profile": "roster_public_profile",
}


def _coerce_bool(cur: Any, *, default: bool = False) -> bool:
    if isinstance(cur, bool):
        return cur
    if cur is None:
        return default
    if isinstance(cur, (int, float)) and not isinstance(cur, bool):
        return cur != 0
    text = str(cur).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return default


def _cfg_to_webui(cfg: CommunityStatsConfig) -> dict[str, Any]:
    return {
        "community_stats_enabled": cfg.enabled,
        "community_stats_endpoint": cfg.endpoint,
        "community_stats_token": cfg.token,
        "community_stats_interval_sec": cfg.interval_sec,
        "community_stats_roster_public_qq": cfg.roster_public_qq,
        "community_stats_roster_public_profile": cfg.roster_public_profile,
    }


def _webui_to_cfg(data: dict[str, Any]) -> CommunityStatsConfig:
    return CommunityStatsConfig(
        enabled=bool(data["community_stats_enabled"]),
        endpoint=str(data.get("community_stats_endpoint") or ""),
        token=str(data.get("community_stats_token") or ""),
        interval_sec=int(data["community_stats_interval_sec"]),
        roster_public_qq=bool(data["community_stats_roster_public_qq"]),
        roster_public_profile=bool(data["community_stats_roster_public_profile"]),
    )


def _field_row(key: str, cur: Any) -> dict[str, Any]:
    model_key = _WEBUI_TO_MODEL[key]
    f = CommunityStatsConfig.model_fields[model_key]
    default_value = None if f.default is PydanticUndefined else f.default
    row: dict[str, Any] = {
        "name": key,
        "label": _FIELD_LABELS.get(key, key),
        "kind": "string",
        "required": bool(f.is_required()),
        "description": normalize_field_description(str(f.description or "")),
        "env_key": _FIELD_TO_ENV[key],
        "default": default_value,
        "current": cur,
    }
    if key == "community_stats_enabled":
        row["kind"] = "bool"
        row["current"] = _coerce_bool(cur, default=True)
        row["description"] = field_help(
            "是否向社区中心上报本机在线情况",
            "开启后「统计与语料」页可看到全网大致数据；关闭不影响牛牛聊天",
            "默认开启；单进程总机上报，分片 worker 不上报",
        )
    elif key == "community_stats_endpoint":
        row["description"] = field_help(
            "在线统计要提交到的网址",
            "官方地址一般无需修改；主站不可用时程序会自动尝试备站",
        )
    elif key == "community_stats_token":
        row["description"] = field_help(
            "提交统计时附带的访问口令",
            "公开统计服务通常可留空；运营方发了专用口令再填写",
        )
    elif key == "community_stats_interval_sec":
        row["kind"] = "enum"
        row["choices"] = _INTERVAL_CHOICES
        row["current"] = str(int(cur)) if cur is not None else _INTERVAL_CHOICES[2]
        row["description"] = field_help(
            "每隔多久上报一次在线情况",
            "例如 5 分钟；间隔越短请求越频繁，越长则页面数据更新越慢",
        )
    elif key in ("community_stats_roster_public_qq", "community_stats_roster_public_profile"):
        row["kind"] = "bool"
        row["current"] = _coerce_bool(cur)
    return row


def community_stats_payload(*, current_values: dict[str, Any] | None = None) -> dict[str, Any]:
    data = _cfg_to_webui(get_community_stats_config())
    if current_values is not None:
        data = {**data, **current_values}
    fields = [_field_row(k, data.get(k)) for k in _FIELD_NAMES]
    return {
        "plugin": COMMUNITY_STATS_SECTION_ID,
        "module": "src.features.community_stats",
        "hot_reload": True,
        "fields": fields,
        "field_groups": [
            {
                "id": "reporting",
                "title": "在线统计上报",
                "field_names": [
                    "community_stats_enabled",
                    "community_stats_endpoint",
                    "community_stats_token",
                    "community_stats_interval_sec",
                ],
            },
            {
                "id": "roster",
                "title": "社区主站展示",
                "field_names": [
                    "community_stats_roster_public_qq",
                    "community_stats_roster_public_profile",
                ],
            },
        ],
    }


def _normalize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(patch)
    if "community_stats_interval_sec" in out:
        try:
            out["community_stats_interval_sec"] = int(out["community_stats_interval_sec"])
        except (TypeError, ValueError) as e:
            raise ValueError("community_stats_interval_sec 须为整数秒") from e
    if "community_stats_enabled" in out:
        out["community_stats_enabled"] = _coerce_bool(out["community_stats_enabled"], default=True)
    for key in ("community_stats_roster_public_qq", "community_stats_roster_public_profile"):
        if key in out:
            out[key] = _coerce_bool(out[key])
    return out


def apply_community_stats_patch(patch: dict[str, Any]) -> dict[str, Any]:
    patch = _normalize_patch(patch)
    allowed = set(_FIELD_NAMES)
    for k in patch:
        if k not in allowed:
            raise ValueError(f"未知配置项: {k}")
    merged = {**_cfg_to_webui(get_community_stats_config()), **patch}
    validated = _webui_to_cfg(merged)
    webui_validated = _cfg_to_webui(validated)
    items = {_FIELD_TO_ENV[k]: env_value_to_str(webui_validated[k]) for k in patch}
    upsert_repo_settings_items(items)
    try:
        from src.features.community_stats.config import clear_community_stats_config_cache

        clear_community_stats_config_cache()
    except Exception:
        pass
    try:
        from nonebot import logger

        from src.features.community_stats.scheduler import schedule_reload_community_stats_reporter

        schedule_reload_community_stats_reporter()
        logger.info("community_stats: WebUI 已写入配置，在线统计上报已热重载")
    except Exception as e:
        from nonebot import logger

        logger.warning("community_stats hot reload failed: {}", e)
    return community_stats_payload(current_values=webui_validated)
