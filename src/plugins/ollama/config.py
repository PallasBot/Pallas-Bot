from pydantic import BaseModel, Field

from src.console.webui import install_hot_reload_config, plugin_config_proxy
from src.console.webui.field_help import field_help


class Config(BaseModel, extra="ignore"):
    ai_server_host: str = Field(
        default="127.0.0.1",
        description=field_help(
            "已弃用",
            "请配置全局 AI_SERVER_HOST / LLM_AI_SERVER_HOST",
        ),
    )
    ai_server_port: int = Field(
        default=9099,
        description=field_help("已弃用", "请配置全局 AI_SERVER_PORT / LLM_AI_SERVER_PORT"),
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
        description="已弃用：默认走 /api/v1/chat/completions。",
    )
    ollama_del_session_endpoint: str = Field(
        default="/api/ollama/del_session",
        description="已弃用：默认走统一 LLM delete session。",
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
    from src.features.llm.config import llm_server_base_url

    _ = cfg
    return llm_server_base_url()
