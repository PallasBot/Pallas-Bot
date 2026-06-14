from __future__ import annotations

from pydantic import BaseModel, Field

from src.console.webui import install_hot_reload_config, plugin_config_proxy


class Config(BaseModel, extra="ignore"):
    spy_min_players: int = Field(default=4, ge=3, le=20, description="最少开局人数")
    spy_max_players: int = Field(default=12, ge=4, le=30, description="房间人数上限")
    spy_default_undercovers: int = Field(default=1, ge=1, le=3, description="默认卧底人数")
    spy_show_role_default: bool = Field(
        default=False,
        description="私聊发词时是否附带身份",
    )
    spy_room_cleanup_sec: int = Field(
        default=600,
        ge=60,
        le=86400,
        description="对局结束后空房间自动清理等待秒数",
    )
    spy_email_fallback: bool = Field(
        default=True,
        description="私聊/临时会话失败时，复用 bot_status SMTP 向玩家 QQ 邮箱发词与投票说明。",
    )


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_spy_config = plugin_webui.get
reload_spy_plugin_config = plugin_webui.reload
plugin_config = plugin_config_proxy(get_spy_config)
