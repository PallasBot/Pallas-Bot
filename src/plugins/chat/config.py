from pydantic import AliasChoices, BaseModel, Field

from src.console.webui import install_hot_reload_config, plugin_config_proxy


class Config(BaseModel, extra="ignore"):
    ai_server_host: str = Field(
        default="127.0.0.1",
        description="已弃用：请配置全局 AI_SERVER_HOST / LLM_AI_SERVER_HOST。",
    )
    ai_server_port: int = Field(
        default=9099,
        description="已弃用：请配置全局 AI_SERVER_PORT / LLM_AI_SERVER_PORT。",
    )
    chat_enable: bool = Field(
        default=False,
        validation_alias=AliasChoices("chat_enable", "llm_chat_enable"),
        description="已弃用：未配置 LLM_CHAT_ENABLED 时启用遗留 RWKV 酒后聊天。",
    )
    chat_endpoint: str = Field(default="/api/chat", description="遗留 RWKV 聊天接口路径。")
    del_session_endpoint: str = Field(
        default="/api/del_session",
        description="遗留 RWKV 醒酒清会话路径。",
    )
    tts_enable: bool = Field(default=False, description="酒后 TTS 暂未接入统一网关，保留配置占位。")


def on_chat_config_reload(cfg: Config) -> None:
    from src.plugins.help.plugin_availability import invalidate_plugin_help_availability_cache

    invalidate_plugin_help_availability_cache()


plugin_webui = install_hot_reload_config(Config, config_module=__name__, on_reload=on_chat_config_reload)
get_chat_config = plugin_webui.get
plugin_config = plugin_config_proxy(get_chat_config)
