from pydantic import AliasChoices, BaseModel, Field

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
    llm_chat_enable: bool = Field(
        default=False,
        validation_alias=AliasChoices("llm_chat_enable", "ollama_enable"),
        description=field_help(
            "是否启用 @牛牛 LLM 闲聊",
            "开启前请确认 AI 服务已部署且 LLM 推理可用",
        ),
    )
    llm_chat_system_prompt_path: str = Field(
        default="",
        validation_alias=AliasChoices("llm_chat_system_prompt_path", "ollama_system_prompt_path"),
        description=field_help(
            "自定义 system prompt 文件路径",
            "留空使用 compile_persona_prompt 默认；可为相对仓库根的路径",
        ),
    )
    llm_chat_min_priority: int = Field(
        default=50,
        ge=1,
        le=99,
        validation_alias=AliasChoices("llm_chat_min_priority", "ollama_min_priority"),
        description=field_help(
            "LLM 闲聊指令优先级（数值越大越靠后）",
            "群内 @ 闲聊默认 51；卧底述词等优先于 LLM 闲聊",
        ),
    )
    llm_model_unload_endpoint: str = Field(
        default="/api/ollama/unload",
        validation_alias=AliasChoices("llm_model_unload_endpoint", "ollama_unload_endpoint"),
        description="已弃用：模型管理仍走 AI 仓 legacy 路径。",
    )
    llm_model_endpoint: str = Field(
        default="/api/ollama/model",
        validation_alias=AliasChoices("llm_model_endpoint", "ollama_model_endpoint"),
        description="已弃用：模型管理仍走 AI 仓 legacy 路径。",
    )
    llm_chat_endpoint: str = Field(
        default="/api/ollama/chat",
        validation_alias=AliasChoices("llm_chat_endpoint", "ollama_chat_endpoint"),
        description="已弃用：默认走 /api/v1/chat/completions。",
    )
    llm_del_session_endpoint: str = Field(
        default="/api/ollama/del_session",
        validation_alias=AliasChoices("llm_del_session_endpoint", "ollama_del_session_endpoint"),
        description="已弃用：默认走统一 LLM delete session。",
    )


def on_llm_chat_config_reload(cfg: Config) -> None:
    import src.plugins.llm_chat.chat_message as chat_pkg
    from src.plugins.help.plugin_availability import invalidate_plugin_help_availability_cache

    invalidate_plugin_help_availability_cache()
    chat_pkg.refresh_server_url(cfg)
    from src.plugins.llm_chat.prompts import clear_system_prompt_cache

    clear_system_prompt_cache()


plugin_webui = install_hot_reload_config(
    Config,
    config_module=__name__,
    on_reload=on_llm_chat_config_reload,
)
get_llm_chat_config = plugin_webui.get
reload_llm_chat_config = plugin_webui.reload
clear_llm_chat_config_cache = plugin_webui.clear_cache
plugin_config = plugin_config_proxy(get_llm_chat_config)

get_ollama_config = get_llm_chat_config
reload_ollama_config = reload_llm_chat_config
clear_ollama_config_cache = clear_llm_chat_config_cache
on_ollama_config_reload = on_llm_chat_config_reload


def llm_chat_server_url(cfg: Config | None = None) -> str:
    from src.features.llm.config import llm_server_base_url

    _ = cfg
    return llm_server_base_url()


ollama_server_url = llm_chat_server_url
