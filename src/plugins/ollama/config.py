from pydantic import BaseModel, Field

from src.console.webui import install_hot_reload_config, plugin_config_proxy
from src.console.webui.field_help import field_help


class Config(BaseModel, extra="ignore"):
    ai_server_host: str = Field(
        default="127.0.0.1",
        description=field_help(
            "Pallas-Bot-AI 服务地址",
            "Docker 全栈填服务名 pallasbot-ai；本机填 127.0.0.1",
        ),
    )
    ai_server_port: int = Field(
        default=9099,
        description=field_help("AI 服务端口", "须与后端监听端口一致"),
    )
    ollama_enable: bool = Field(
        default=False,
        description=field_help(
            "是否启用 @牛牛 Ollama 多轮对话",
            "开启前请确认 AI 服务已部署且 Ollama 可用",
        ),
    )
    ollama_chat_endpoint: str = Field(
        default="/api/ollama/chat",
        description="提交 Ollama 对话任务的 HTTP 路径。",
    )
    ollama_del_session_endpoint: str = Field(
        default="/api/ollama/del_session",
        description="清除 Ollama 会话记忆的 HTTP 路径。",
    )
    ollama_unload_endpoint: str = Field(
        default="/api/ollama/unload",
        description="卸载 Ollama 模型的 HTTP 路径。",
    )
    ollama_model_endpoint: str = Field(
        default="/api/ollama/model",
        description="查询或热更换 Ollama 模型的 HTTP 路径。",
    )
    ollama_system_prompt_path: str = Field(
        default="",
        description=field_help(
            "自定义 system prompt 文件路径",
            "留空使用插件内置 system_prompt.txt；可为相对仓库根的路径",
        ),
    )
    ollama_min_priority: int = Field(
        default=50,
        ge=1,
        le=99,
        description=field_help(
            "Ollama 指令优先级（数值越大越靠后）",
            "群内 @ 闲聊默认 51；卧底述词等优先于 Ollama",
        ),
    )


def on_ollama_config_reload(cfg: Config) -> None:
    import src.plugins.ollama.chat_message as chat_pkg
    from src.plugins.help.plugin_availability import invalidate_plugin_help_availability_cache

    invalidate_plugin_help_availability_cache()
    chat_pkg.refresh_server_url(cfg)
    from src.plugins.ollama.prompts import clear_system_prompt_cache

    clear_system_prompt_cache()


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_ollama_config_reload,
)
get_ollama_config = plugin_webui.get
reload_ollama_config = plugin_webui.reload
clear_ollama_config_cache = plugin_webui.clear_cache
plugin_config = plugin_config_proxy(get_ollama_config)


def ollama_server_url(cfg: Config | None = None) -> str:
    c = cfg or get_ollama_config()
    return f"http://{c.ai_server_host}:{c.ai_server_port}"
