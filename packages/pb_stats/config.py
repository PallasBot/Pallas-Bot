"""在线统计插件 WebUI 配置（原通用配置 community_stats 段）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pallas.console.webui import plugin_config_proxy
from pallas.console.webui.field_help import field_help
from pallas.console.webui.registry import PluginWebuiConfigHooks, register_plugin_webui_config

FIELD_TO_ENV: dict[str, str] = {
    "enabled": "PALLAS_COMMUNITY_STATS_ENABLED",
    "endpoint": "PALLAS_COMMUNITY_STATS_ENDPOINT",
    "token": "PALLAS_COMMUNITY_STATS_TOKEN",
    "interval_sec": "PALLAS_COMMUNITY_STATS_INTERVAL_SEC",
    "roster_public_qq": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_QQ",
    "roster_public_profile": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_PROFILE",
    "corpus_hot_snapshot_interval_sec": "PALLAS_COMMUNITY_STATS_CORPUS_HOT_SNAPSHOT_INTERVAL_SEC",
}

IntervalSec = Literal[60, 120, 300, 600, 900, 1800, 3600]


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(
        default=True,
        json_schema_extra={"label": "上报在线统计"},
        description=field_help(
            "是否向社区中心上报本机在线情况",
            "开启后「统计与语料」页可看到全网大致数据；关闭不影响牛牛聊天",
            "默认开启；单进程总机上报，分片 worker 不上报",
        ),
    )
    endpoint: str = Field(
        default="https://stats.pallasbot.top/v1/heartbeat",
        json_schema_extra={"label": "统计上报地址", "ui_group": "advanced"},
        description=field_help(
            "在线统计要提交到的网址",
            "官方地址一般无需修改；主站不可用时程序会自动尝试备站",
        ),
    )
    token: str = Field(
        default="",
        json_schema_extra={"label": "统计上报口令", "secret": True, "ui_group": "advanced"},
        description=field_help(
            "提交统计时附带的访问口令",
            "公开统计服务通常可留空；运营方发了专用口令再填写",
        ),
    )
    interval_sec: IntervalSec = Field(
        default=300,
        json_schema_extra={"label": "上报间隔", "ui_group": "reporting"},
        description=field_help(
            "每隔多久上报一次在线情况",
            "例如 5 分钟；间隔越短请求越频繁，越长则页面数据更新越慢",
        ),
    )
    roster_public_qq: bool = Field(
        default=False,
        json_schema_extra={"label": "公开牛牛 QQ", "ui_group": "roster"},
        description=field_help(
            "是否在社区主站气泡墙展示牛牛 QQ",
            "可与头像昵称分开控制",
            "默认关闭",
        ),
    )
    roster_public_profile: bool = Field(
        default=True,
        json_schema_extra={"label": "公开牛牛头像昵称", "ui_group": "roster"},
        description=field_help(
            "是否在社区主站气泡墙展示牛牛昵称与头像",
            "默认开启，与在线统计上报一致；不需要展示时在此关闭",
        ),
    )
    corpus_hot_snapshot_interval_sec: int = Field(
        default=900,
        ge=300,
        le=86400,
        json_schema_extra={"label": "热词快照间隔（秒）", "ui_hidden": True},
        description="心跳附带本机热词快照的最小间隔（秒）。",
    )


def get_pb_stats_config() -> Config:
    from pallas.product.community_stats.config import get_community_stats_config

    raw = get_community_stats_config().model_dump(mode="python")
    interval = int(raw.get("interval_sec") or 300)
    if interval not in (60, 120, 300, 600, 900, 1800, 3600):
        interval = 300
    raw["interval_sec"] = interval
    return Config.model_validate(raw)


def clear_pb_stats_config_cache() -> None:
    from pallas.product.community_stats.config import clear_community_stats_config_cache

    clear_community_stats_config_cache()


def on_pb_stats_config_reload(cfg: Config) -> None:
    from nonebot import logger

    try:
        from pallas.product.community_stats.scheduler import schedule_reload_community_stats_reporter

        schedule_reload_community_stats_reporter()
        logger.info("pb_stats: config saved, hot reloaded")
    except Exception as e:
        logger.warning("pb_stats hot reload failed: {}", e)


def reload_pb_stats_config() -> None:
    clear_pb_stats_config_cache()
    on_pb_stats_config_reload(get_pb_stats_config())


_hooks = PluginWebuiConfigHooks(
    get=get_pb_stats_config,
    reload=reload_pb_stats_config,
    clear_cache=clear_pb_stats_config_cache,
)
for _key in ("packages.pb_stats", "packages.pb_stats.config", "pb_stats"):
    register_plugin_webui_config(_key, _hooks)

plugin_config = plugin_config_proxy(get_pb_stats_config)
