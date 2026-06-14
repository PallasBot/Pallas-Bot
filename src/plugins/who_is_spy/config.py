from __future__ import annotations

from pydantic import BaseModel, Field

from src.console.webui import install_hot_reload_config, plugin_config_proxy


class Config(BaseModel, extra="ignore"):
    spy_min_players: int = Field(default=4, ge=3, le=20, description="最少开局人数")
    spy_max_players: int = Field(default=12, ge=4, le=30, description="房间人数上限")
    spy_default_undercovers: int = Field(default=1, ge=1, le=3, description="默认卧底人数")
    spy_default_blanks: int = Field(
        default=0,
        ge=0,
        le=2,
        description="默认白板人数（无词，不计入平民/卧底胜负计数）",
    )
    spy_show_role_default: bool = Field(
        default=False,
        description="私聊发词时是否附带平民/卧底身份（false 为暗牌，只发词）",
    )
    spy_word_avoid_recent: int = Field(
        default=10,
        ge=0,
        le=100,
        description="同群最近 N 局词对不重复；0 关闭",
    )
    spy_auto_vote_when_all_spoken: bool = Field(
        default=True,
        description="存活玩家均 @牛牛 述词后自动进入私聊投票",
    )
    spy_speak_max_len: int = Field(
        default=120,
        ge=20,
        le=500,
        description="述词复盘单条最大字数（超出截断）",
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
