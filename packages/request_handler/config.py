from pydantic import BaseModel, Field

from pallas.console.webui import install_hot_reload_config, plugin_config_proxy


class Config(BaseModel, extra="ignore"):
    request_handler_notify_superusers: bool = Field(
        default=True,
        description="除号主外，是否额外通知不在号主列表中的 SUPERUSER（号主始终通知；默认开启）。",
    )
    request_handler_poll_doubt_friends: bool = Field(
        default=True,
        description="是否定时检查「可能被风控拦截」的好友申请，并私聊提醒管理员（约每 4 小时一轮）。",
    )


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_request_handler_config = plugin_webui.get
plugin_config = plugin_config_proxy(get_request_handler_config)
