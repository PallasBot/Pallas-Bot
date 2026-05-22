from pydantic import BaseModel, Field

from src.common.webui import install_hot_reload_config, plugin_config_proxy


class Config(BaseModel, extra="ignore"):
    ai_server_host: str = Field(default="127.0.0.1", description="Pallas-Bot-AI（或兼容服务）的主机地址。")
    ai_server_port: int = Field(default=9099, description="AI 服务监听端口。")
    chat_enable: bool = Field(default=False, description="是否启用文字对话（需 AI 服务已部署且可访问）。")
    chat_endpoint: str = Field(default="/api/chat", description="发起聊天的 HTTP 路径。")
    del_session_endpoint: str = Field(default="/api/del_session", description="清除会话记忆的 HTTP 路径。")
    tts_enable: bool = Field(default=False, description="是否在对话中启用服务端语音合成（依赖 AI 端能力）。")


def on_chat_config_reload(cfg: Config) -> None:
    import src.plugins.chat as chat_pkg

    chat_pkg.refresh_server_url(cfg)


plugin_webui = install_hot_reload_config(Config, config_module=__name__, on_reload=on_chat_config_reload)
get_chat_config = plugin_webui.get
plugin_config = plugin_config_proxy(get_chat_config)
