from pydantic import BaseModel, Field

from src.common.webui import install_hot_reload_config, plugin_config_proxy


class Config(BaseModel, extra="ignore"):
    bots: set[int] = Field(
        default_factory=set,
        description=(
            "当前已连接的本 Bot QQ 号集合，随连接/断开自动维护；"
            "用于识别群内「另一只牛牛」并拦截其消息。一般无需手动填写。"
        ),
    )


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_block_config = plugin_webui.get
plugin_config = plugin_config_proxy(get_block_config)
