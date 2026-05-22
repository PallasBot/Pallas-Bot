from pydantic import BaseModel, Field

from src.common.webui import install_hot_reload_config, plugin_config_proxy


class Config(BaseModel, extra="ignore"):
    enable_kick_ban: bool = Field(
        default=True,
        description="牛牛被移出群后，是否自动将其加入黑名单。",
    )


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_greeting_config = plugin_webui.get
plugin_config = plugin_config_proxy(get_greeting_config)
